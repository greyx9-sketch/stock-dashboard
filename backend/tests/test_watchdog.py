"""알림 메시지 구성 테스트.

메시지 한 통만 보고 **무엇이 어떻게 고장났는지** 알 수 있어야 한다. "오류 발생" 한 줄만
오는 알림은 결국 서버에 들어가 봐야 하므로 없는 것과 큰 차이가 없다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from watchdog import _body, compose  # noqa: E402


PAYLOAD = {
    "status": "degraded",
    "summary": "현재가: 장중인데 12분째 갱신이 없습니다.",
    "checks": [
        {"name": "DB", "status": "ok", "detail": "정상"},
        {"name": "현재가", "status": "degraded", "detail": "장중인데 12분째 갱신이 없습니다."},
    ],
    "recent_errors": [{"at": "2026-08-20T01:00:00+00:00", "path": "/api/prices", "status": 500, "detail": ""}],
}


def test_message_names_the_broken_part():
    text = compose("degraded", PAYLOAD["summary"], PAYLOAD)
    assert "현재가" in text
    assert "12분째" in text


def test_message_skips_healthy_checks():
    """정상 항목까지 나열하면 문제가 묻힌다."""
    text = compose("degraded", PAYLOAD["summary"], PAYLOAD)
    assert "DB" not in text


def test_message_includes_site_url():
    """알림을 받고 바로 확인하러 갈 수 있어야 한다."""
    assert "129.225.188.89" in compose("down", "앱이 응답하지 않습니다", None)


def test_message_works_without_payload():
    """앱이 죽으면 상세 응답 자체가 없다. 그때도 메시지는 만들어져야 한다."""
    text = compose("down", "앱이 응답하지 않습니다", None)
    assert "앱이 응답하지 않습니다" in text
    assert "DOWN" in text


def test_discord_and_slack_use_different_body_keys():
    """본문 키를 틀리면 웹훅이 400 을 내고 알림이 조용히 사라진다."""
    discord = json.loads(_body("https://discord.com/api/webhooks/1/abc", "안녕"))
    slack = json.loads(_body("https://hooks.slack.com/services/T/B/x", "안녕"))
    assert discord == {"content": "안녕"}
    assert slack == {"text": "안녕"}


def test_unknown_host_falls_back_to_text():
    assert json.loads(_body("https://example.com/hook", "안녕")) == {"text": "안녕"}


# ---------------------------------------------------------------- 텔레그램

import watchdog  # noqa: E402


def test_telegram_body_carries_the_chat_id():
    """텔레그램은 대화방 번호가 본문에 있어야 한다. 없으면 400 이고 알림이 조용히 사라진다."""
    url = "https://api.telegram.org/bot123:ABC/sendMessage?chat_id=987654"
    assert json.loads(_body(url, "안녕")) == {"chat_id": "987654", "text": "안녕"}


def test_telegram_is_not_confused_with_slack():
    """주소를 보고 형식을 고른다. 텔레그램에 text 만 보내면 받는 쪽이 거절한다."""
    telegram = json.loads(_body("https://api.telegram.org/botX/sendMessage?chat_id=1", "x"))
    assert "chat_id" in telegram


def test_env_line_is_replaced_not_duplicated(tmp_path, monkeypatch):
    """같은 키가 두 줄이면 나중 줄이 이기거나 툴마다 다르게 읽는다. 한 줄만 남아야 한다."""
    env = tmp_path / ".env"
    env.write_text("A=1\nALERT_WEBHOOK_URL=old\nB=2\n", encoding="utf-8")
    monkeypatch.setattr(watchdog, "ENV_FILE", env)

    watchdog._write_env("ALERT_WEBHOOK_URL", "new")

    lines = env.read_text(encoding="utf-8").strip().split("\n")
    assert lines == ["A=1", "ALERT_WEBHOOK_URL=new", "B=2"]


def test_env_line_is_appended_when_missing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    monkeypatch.setattr(watchdog, "ENV_FILE", env)

    watchdog._write_env("ALERT_WEBHOOK_URL", "new")

    assert "ALERT_WEBHOOK_URL=new" in env.read_text(encoding="utf-8").split("\n")


def test_env_survives_a_missing_trailing_newline(tmp_path, monkeypatch):
    """마지막 줄에 줄바꿈이 없으면 새 줄이 앞줄에 붙어 버린다. 실제로 겪은 사고다."""
    env = tmp_path / ".env"
    env.write_text("A=1", encoding="utf-8")  # 줄바꿈 없음
    monkeypatch.setattr(watchdog, "ENV_FILE", env)

    watchdog._write_env("ALERT_WEBHOOK_URL", "new")

    lines = [line for line in env.read_text(encoding="utf-8").split("\n") if line]
    assert lines == ["A=1", "ALERT_WEBHOOK_URL=new"]


def test_value_with_percent_is_written_verbatim(tmp_path, monkeypatch):
    """공공데이터포털 키에는 %3D%3D 가 들어 있다. 서식 문자열로 다루면 값이 망가진다 —
    실제로 그렇게 키 끝에 글자가 붙어 종가 수집이 5일 동안 실패했다."""
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    monkeypatch.setattr(watchdog, "ENV_FILE", env)

    tricky = "abc%3D%3D"
    watchdog._write_env("SOME_KEY", tricky)

    assert "SOME_KEY=" + tricky in env.read_text(encoding="utf-8")
