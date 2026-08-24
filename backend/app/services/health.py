"""앱이 지금 정상인지 스스로 판단한다.

오라클 경보는 **가상머신이 멈춘 것**만 잡는다. 서버는 켜져 있는데 앱이 500 을 뿜거나,
토스 토큰이 만료돼 현재가가 멈추거나, 확정 종가 수집이 며칠째 실패하는 상황은
아무도 알려주지 않는다. 사이트를 열어 보고서야 아는 것이 지금까지의 상태였다.

여기서 하는 일은 **판단**뿐이다. 알림을 보내는 것은 `backend/scripts/watchdog.py` 가 맡는다.
판단과 전달을 나눠 두면 화면(경고 띠)과 알림이 같은 근거를 쓰게 된다.

세 단계로 답한다:

| 상태 | 뜻 | 화면 | 알림 |
| --- | --- | --- | --- |
| `ok` | 정상 | 아무것도 안 보인다 | 없음 |
| `degraded` | 일부가 고장났지만 사이트는 뜬다 | 노란 띠 | 보낸다 |
| `down` | 핵심이 죽었다 | 빨간 띠 | 보낸다 |

**애매하면 ok 로 둔다.** 멀쩡한데 자꾸 우는 경보는 며칠 만에 무시하게 되고, 그러면
진짜 고장도 같이 묻힌다.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text

from app.models.base import get_session
from app.services.price_poller import LIVE_PHASES, poller
from app.services.scheduler import scheduler

# 최근 오류를 몇 건까지 들고 있을지. 화면에 보여줄 만큼만 남긴다.
ERROR_BUFFER = 50

# 이 시간 안에 난 오류만 "최근"으로 센다(초).
RECENT_WINDOW_SEC = 30 * 60

# 최근 창 안에 5xx 가 이 수를 넘으면 degraded 로 본다.
# 1 건은 일회성 외부 API 실패일 수 있어 올리지 않는다 — 진짜 고장은 반복된다.
ERROR_THRESHOLD = 3

# 장중인데 현재가를 이만큼 못 받고 있으면 폴러가 멈춘 것으로 본다(초).
# 정규장 폴링 간격이 5초, 연속 실패 시 최대 백오프가 120초라 그보다 넉넉히 잡는다.
POLLER_STALL_SEC = 600

# 확정 종가 수집은 하루 한 번이라 한 번 실패했다고 바로 울리지 않는다.
# 이만큼 지나도록 성공이 없으면 알린다(초).
COLLECTION_STALL_SEC = 36 * 3600


@dataclass
class ServerError:
    """서버가 5xx 로 답한 한 건."""

    at: datetime
    path: str
    status: int
    detail: str


@dataclass
class Health:
    status: str  # ok / degraded / down
    checks: list["Check"] = field(default_factory=list)
    recent_errors: list[ServerError] = field(default_factory=list)

    @property
    def problems(self) -> list["Check"]:
        return [c for c in self.checks if c.status != "ok"]

    def summary(self) -> str:
        """알림 한 줄. 무엇이 문제인지 제목만으로 알 수 있어야 한다."""
        if self.status == "ok":
            return "정상"
        return " / ".join(f"{c.name}: {c.detail}" for c in self.problems)


@dataclass
class Check:
    name: str
    status: str  # ok / degraded / down
    detail: str


_errors: deque[ServerError] = deque(maxlen=ERROR_BUFFER)


def record_error(path: str, status: int, detail: str) -> None:
    """5xx 를 한 건 기록한다. 미들웨어가 부른다."""
    _errors.append(
        ServerError(at=datetime.now(timezone.utc), path=path, status=status, detail=detail[:300])
    )


def recent_errors(now: datetime | None = None) -> list[ServerError]:
    now = now or datetime.now(timezone.utc)
    return [e for e in _errors if (now - e.at).total_seconds() <= RECENT_WINDOW_SEC]


def _worst(statuses: list[str]) -> str:
    """가장 나쁜 상태가 전체 상태가 된다."""
    for level in ("down", "degraded"):
        if level in statuses:
            return level
    return "ok"


def _check_db() -> Check:
    """DB 파일을 실제로 읽어 본다.

    디스크가 차거나 파일 권한이 틀어지면 화면의 모든 목록이 500 이 된다. 이건 `down` 이다 —
    이 상태에서는 사이트가 아무 값도 보여주지 못한다.
    """
    try:
        with get_session() as session:
            session.execute(text("SELECT 1")).scalar_one()
    except Exception as exc:  # DB 는 어떤 이유로든 못 읽으면 치명적이다
        return Check("DB", "down", f"읽을 수 없습니다 — {exc}"[:200])
    return Check("DB", "ok", "정상")


def _check_poller(now: datetime) -> Check:
    """현재가 폴러.

    폴러가 **안 부르는 것이 정상인 경우가 둘** 있다. 둘 다 걸러내지 않으면 멀쩡한데
    운다:

    1. **장이 닫혀 있을 때.** 안 걸러내면 매일 밤 울린다.
    2. **아무도 화면을 안 보고 있을 때.** 폴러는 보고 있는 종목만 부른다
       (`price_poller._tick` 참고). 아무도 안 보고 있으면 장중에도 한 번도 안 부르는
       것이 설계대로다.

    2번이 빠져 있어서 실제로 오작동했다(2026-08-24). 사이트를 아무도 안 열어 둔 채
    미국 프리마켓이 열리자 `down` 이 떴다 — 빨간 띠에 10분마다 텔레그램까지. 폴러는
    멀쩡했고, 종목 하나를 등록하자 12초 만에 `ok` 로 돌아왔다.

    **멀쩡한데 우는 경보는 진짜 고장을 묻는다.** 며칠이면 무시하게 되기 때문이다.
    """
    live = any(state.phase in LIVE_PHASES for state in poller.markets.values())
    last = poller.last_success_at
    error = poller.last_error

    if not live:
        # 장이 닫혀 있어도 마지막 오류는 알려 준다(허용 IP 문제 같은 것은 밤에도 고칠 수 있다).
        if error:
            return Check("현재가", "degraded", f"마지막 호출이 실패했습니다 — {error}"[:200])
        return Check("현재가", "ok", "장 마감 — 갱신하지 않는 것이 정상")

    if poller.watching == 0:
        # 오류는 여기서도 알려 준다 — 마지막 시도가 실패한 채로 조용해진 것일 수 있다.
        if error:
            return Check("현재가", "degraded", f"마지막 호출이 실패했습니다 — {error}"[:200])
        return Check("현재가", "ok", "보고 있는 화면이 없어 부르지 않는 중 — 정상")

    if last is None:
        # 여기까지 왔으면 보고 있는 종목이 있다는 뜻이다. 등록되면 폴러가 즉시 깨어나므로
        # 그러고도 한 번도 못 받았다면 진짜로 멈춘 것이다.
        return Check("현재가", "down", "장중이고 보고 있는 화면도 있는데 한 번도 받지 못했습니다.")

    age = (now - last).total_seconds()
    if age > POLLER_STALL_SEC:
        detail = f"장중인데 {int(age // 60)}분째 갱신이 없습니다."
        if error:
            detail += f" 마지막 오류: {error}"
        return Check("현재가", "down", detail[:200])

    if error:
        return Check("현재가", "degraded", f"최근 호출이 실패했습니다 — {error}"[:200])
    return Check("현재가", "ok", f"{int(age)}초 전 갱신")


def _check_collection(now: datetime) -> Check:
    """KRX 확정 종가 자동 수집.

    실패해도 사이트는 뜬다(어제까지의 데이터가 그대로 있다). 그래서 `down` 이 아니라
    `degraded` 다. 다만 며칠 방치되면 화면의 "확정 종가"가 계속 낡아 간다.
    """
    last = scheduler.last_run
    if last is None:
        return Check("종가 수집", "ok", "아직 실행 전")
    if not last.ok:
        return Check("종가 수집", "degraded", f"마지막 수집 실패 — {last.error}"[:200])

    age = (now - last.started_at).total_seconds()
    if age > COLLECTION_STALL_SEC:
        return Check("종가 수집", "degraded", f"{int(age // 3600)}시간째 수집 기록이 없습니다.")
    return Check("종가 수집", "ok", "정상")


def _check_errors(now: datetime) -> Check:
    recent = recent_errors(now)
    if len(recent) < ERROR_THRESHOLD:
        return Check("서버 오류", "ok", f"최근 30분 {len(recent)}건")
    paths = sorted({e.path for e in recent})[:3]
    return Check(
        "서버 오류",
        "degraded",
        f"최근 30분 {len(recent)}건 — {', '.join(paths)}",
    )


def assess() -> Health:
    """지금 상태를 판단한다. 외부 API 를 부르지 않으므로 즉시 돌아온다."""
    now = datetime.now(timezone.utc)
    checks = [
        _check_db(),
        _check_poller(now),
        _check_collection(now),
        _check_errors(now),
    ]
    return Health(
        status=_worst([c.status for c in checks]),
        checks=checks,
        recent_errors=list(reversed(recent_errors(now)))[:10],
    )


# 프로세스가 언제 떴는지. 자꾸 재시작되고 있는지 판단하는 근거로 쓴다.
STARTED_AT = time.time()


def uptime_seconds() -> float:
    return time.time() - STARTED_AT
