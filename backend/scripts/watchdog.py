#!/usr/bin/env python
"""앱이 고장났을 때 알린다. cron 이 10분마다 돌린다.

**왜 필요한가.** 오라클 경보는 가상머신이 멈춘 것만 잡는다. 서버는 켜져 있는데 앱이
500 을 뿜거나, 토스 허용 IP 가 풀려 현재가가 멈추거나, 확정 종가 수집이 며칠째 실패하는
상황은 아무도 알려주지 않는다. 사이트를 열어 봐야 아는 것이 지금까지의 상태였다.

**무엇을 보는가.** 판단은 앱이 한다 — 이 스크립트는 `/api/health/detail` 을 읽고
그 결과를 전달만 한다. 화면의 경고 띠와 같은 근거를 쓰므로 둘이 어긋나지 않는다.
응답 자체가 오지 않으면(앱이 죽었거나 응답 불능) 그것도 알린다.

**어디로 보내는가.** `.env` 의 `ALERT_WEBHOOK_URL` 로 POST 한다. 디스코드·슬랙 웹훅
주소를 그대로 넣으면 된다(둘의 본문 형식을 자동으로 맞춘다). 비어 있으면 알림은 건너뛰고
상태만 화면에 출력한다 — **주소가 없다고 스크립트가 실패하지는 않는다.**

**같은 문제로 반복해서 울리지 않는다.** 상태와 요약을 파일에 적어 두고, 직전과 같으면
조용히 넘어간다. 10분마다 같은 메일이 오면 며칠 만에 무시하게 되고 진짜 고장도 묻힌다.
회복되면 "정상으로 돌아왔다"를 한 번 보낸다.

사용법:
    ./.venv/bin/python backend/scripts/watchdog.py            # 검사하고 필요하면 알림
    ./.venv/bin/python backend/scripts/watchdog.py --test     # 웹훅이 실제로 닿는지 시험
    ./.venv/bin/python backend/scripts/watchdog.py --dry-run  # 보내지 않고 판단만 출력

cron (서버 시간이 UTC 라는 점에 주의):
    */10 * * * * cd /opt/stock && ./.venv/bin/python backend/scripts/watchdog.py >> /tmp/watchdog.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config import get_settings  # noqa: E402

# 앱은 이 주소로 로컬에서만 듣는다. Caddy(비밀번호)를 거치지 않으므로 인증이 필요 없다.
HEALTH_URL = "http://127.0.0.1:8000/api/health/detail"

# 직전 상태를 적어 두는 곳. 같은 문제로 반복해 울리지 않기 위한 것이다.
STATE_FILE = PROJECT_ROOT / "data" / "watchdog_state.json"

TIMEOUT_SEC = 15

SITE_URL = "http://129.225.188.89"


def _fetch_health(url: str = None) -> tuple[str, str, dict | None]:
    """(상태, 요약, 원본) 을 돌려준다. 응답 자체를 못 받으면 그것도 하나의 상태다."""
    try:
        with urllib.request.urlopen(url or HEALTH_URL, timeout=TIMEOUT_SEC) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        # 앱이 죽었거나 포트가 닫혔다. 가장 심각한 경우다.
        return "down", f"앱이 응답하지 않습니다 — {exc.reason}", None
    except Exception as exc:  # JSON 이 깨졌거나 예상 밖의 응답
        return "down", f"가동 상태를 읽을 수 없습니다 — {exc}", None

    return payload.get("status", "down"), payload.get("summary", ""), payload


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _body(url: str, text: str) -> bytes:
    """디스코드와 슬랙은 본문 키가 다르다. 주소로 구분한다.

    둘 다 아니면 슬랙 형식(`text`)으로 보낸다 — 웹훅을 받는 서비스 대부분이 이 모양을
    이해하고, 아니어도 본문에 내용이 그대로 들어 있어 사람이 읽을 수는 있다.
    """
    key = "content" if "discord.com" in url or "discordapp.com" in url else "text"
    return json.dumps({key: text}, ensure_ascii=False).encode("utf-8")


def notify(url: str, text: str) -> bool:
    request = urllib.request.Request(
        url,
        data=_body(url, text),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        print(f"알림 전송 실패: HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        print(f"알림 전송 실패: {exc.reason}")
    return False


def compose(status: str, summary: str, payload: dict | None) -> str:
    """사람이 메시지 한 통만 보고 무엇을 할지 알 수 있게 쓴다."""
    mark = {"down": "🔴", "degraded": "🟡", "ok": "🟢"}.get(status, "⚪")
    now = datetime.now(timezone.utc).astimezone().strftime("%m/%d %H:%M")

    lines = [f"{mark} [증권 대시보드] {status.upper()} · {now}", summary or "(내용 없음)"]

    if payload:
        problems = [c for c in payload.get("checks", []) if c.get("status") != "ok"]
        if problems:
            lines.append("")
            lines += [f"· {c['name']} — {c['detail']}" for c in problems]
        errors = payload.get("recent_errors") or []
        if errors:
            lines.append("")
            lines.append(f"최근 오류 {len(errors)}건 (새 것부터):")
            lines += [f"· {e['status']} {e['path']}" for e in errors[:5]]

    lines.append("")
    lines.append(SITE_URL)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="앱 가동 상태를 검사하고 필요하면 알린다.")
    parser.add_argument("--test", action="store_true", help="시험 메시지를 한 번 보낸다")
    parser.add_argument("--dry-run", action="store_true", help="보내지 않고 판단만 출력한다")
    # 기본은 배포된 서버(8000). 개발 중 다른 포트로 띄웠을 때만 바꾼다.
    parser.add_argument("--url", default=HEALTH_URL, help=f"가동 상태 주소 (기본 {HEALTH_URL})")
    args = parser.parse_args()

    webhook = get_settings().alert_webhook_url

    if args.test:
        if not webhook:
            print("ALERT_WEBHOOK_URL 이 비어 있습니다. .env 에 웹훅 주소를 넣어 주세요.")
            return 1
        ok = notify(webhook, "🟢 [증권 대시보드] 알림 연결 시험입니다. 이 메시지가 보이면 정상입니다.")
        print("시험 메시지를 보냈습니다." if ok else "시험 메시지를 보내지 못했습니다.")
        return 0 if ok else 1

    status, summary, payload = _fetch_health(args.url)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {status} — {summary}")

    state = _load_state()
    previous = state.get("status", "ok")
    # 같은 상태에서 내용까지 같으면 다시 울리지 않는다. 내용이 바뀌면 새 문제로 본다.
    same = previous == status and state.get("summary") == summary

    if status == "ok":
        if previous != "ok":
            message = f"🟢 [증권 대시보드] 정상으로 돌아왔습니다.\n\n{SITE_URL}"
            if args.dry_run:
                print("--- 보낼 내용 ---\n" + message)
            elif webhook:
                notify(webhook, message)
        _save_state({"status": status, "summary": summary})
        return 0

    message = compose(status, summary, payload)
    if args.dry_run:
        print("--- 보낼 내용 ---\n" + message)
    elif same:
        print("직전과 같은 문제라 알림을 보내지 않습니다.")
    elif not webhook:
        print("ALERT_WEBHOOK_URL 이 비어 있어 알림을 건너뜁니다. (.env 참고)")
    else:
        notify(webhook, message)

    _save_state({"status": status, "summary": summary})
    # 상태가 나빠도 스크립트 자체는 성공이다. cron 이 실패로 보고 메일을 또 만들 이유가 없다.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
