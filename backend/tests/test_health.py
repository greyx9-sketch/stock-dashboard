"""가동 상태 판단 테스트.

여기서 중요한 것은 **오작동하지 않는 것**이다. 멀쩡한데 자꾸 우는 경보는 며칠 만에
무시하게 되고, 그러면 진짜 고장도 같이 묻힌다. 그래서 임계값과 "장 마감에는 조용하다"는
규칙을 못 박아 둔다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import health
from app.services.health import (
    Check,
    _check_collection,
    _check_errors,
    _check_poller,
    _worst,
    record_error,
)


def setup_function() -> None:
    """최근 오류 기록은 모듈 전역이다. 테스트끼리 새지 않게 매번 비운다."""
    health._errors.clear()


# ---------------------------------------------------------------- 전체 상태


def test_worst_wins():
    """항목 하나라도 down 이면 전체가 down 이다. 평균을 내지 않는다."""
    assert _worst(["ok", "ok", "ok"]) == "ok"
    assert _worst(["ok", "degraded"]) == "degraded"
    assert _worst(["ok", "degraded", "down"]) == "down"


def test_summary_lists_only_problems():
    """알림 제목에 정상 항목까지 넣으면 무엇이 문제인지 한눈에 안 보인다."""
    result = health.Health(
        status="degraded",
        checks=[Check("DB", "ok", "정상"), Check("현재가", "degraded", "멈췄습니다")],
    )
    assert result.summary() == "현재가: 멈췄습니다"


def test_summary_is_plain_when_ok():
    assert health.Health(status="ok").summary() == "정상"


# ---------------------------------------------------------------- 오류 누적


def test_single_error_does_not_raise_alarm():
    """한 건은 외부 API 의 일회성 실패일 수 있다. 진짜 고장은 반복된다."""
    now = datetime.now(timezone.utc)
    record_error("/api/stocks", 500, "boom")
    assert _check_errors(now).status == "ok"


def test_repeated_errors_flip_to_degraded():
    now = datetime.now(timezone.utc)
    for _ in range(health.ERROR_THRESHOLD):
        record_error("/api/stocks", 500, "boom")
    check = _check_errors(now)
    assert check.status == "degraded"
    # 어느 경로가 문제인지 알려 줘야 서버에 들어가지 않고도 짐작할 수 있다.
    assert "/api/stocks" in check.detail


def test_old_errors_fall_out_of_the_window():
    """어제 난 오류로 오늘 울리면 안 된다. 창을 벗어난 것은 세지 않는다."""
    now = datetime.now(timezone.utc)
    for _ in range(health.ERROR_THRESHOLD + 2):
        record_error("/api/stocks", 500, "boom")
    later = now + timedelta(seconds=health.RECENT_WINDOW_SEC + 60)
    assert _check_errors(later).status == "ok"


def test_error_detail_is_truncated():
    """스택트레이스가 통째로 들어오면 알림 메시지가 읽을 수 없게 길어진다."""
    record_error("/api/stocks", 500, "x" * 5000)
    assert len(health._errors[0].detail) <= 300


def test_buffer_does_not_grow_without_bound():
    """오류가 쏟아져도 메모리를 계속 먹지 않는다(서버 메모리가 1GB 다)."""
    for i in range(health.ERROR_BUFFER * 3):
        record_error(f"/api/{i}", 500, "boom")
    assert len(health._errors) == health.ERROR_BUFFER


# ---------------------------------------------------------------- 현재가 폴러
#
# 폴러가 **안 부르는 것이 정상인 경우**를 오작동으로 읽지 않는지 본다. 여기가 이 파일에서
# 가장 값어치 있는 부분이다 — 실제로 한 번 틀렸다(2026-08-24, 아래 회귀 테스트).


class _FakeMarket:
    def __init__(self, phase: str) -> None:
        self.phase = phase


def _fake_poller(monkeypatch, *, phase: str, watching: int, last=None, error=None) -> None:
    """폴러를 통째로 흉내 낸다. 진짜 폴러는 이벤트 루프와 외부 API 를 붙들고 있다."""
    monkeypatch.setattr(health.poller, "_markets", {"US": _FakeMarket(phase)}, raising=False)
    monkeypatch.setattr(type(health.poller), "markets", property(lambda self: {"US": _FakeMarket(phase)}))
    monkeypatch.setattr(type(health.poller), "watching", property(lambda self: watching))
    monkeypatch.setattr(type(health.poller), "last_success_at", property(lambda self: last))
    monkeypatch.setattr(type(health.poller), "last_error", property(lambda self: error))


def test_closed_market_is_not_an_alarm(monkeypatch):
    """장이 닫혀 있으면 안 부르는 것이 정상이다. 아니면 매일 밤 운다."""
    _fake_poller(monkeypatch, phase="CLOSED", watching=0)
    assert _check_poller(datetime.now(timezone.utc)).status == "ok"


def test_nobody_watching_is_not_an_alarm(monkeypatch):
    """**회귀(2026-08-24).** 장중이어도 보고 있는 화면이 없으면 폴러는 안 부른다.

    폴러는 등록된 종목만 부른다(`price_poller._tick`). 아무도 사이트를 안 열어 둔 채
    미국 프리마켓이 열리자 `down` 이 떴다 — 빨간 띠에 10분마다 텔레그램까지. 폴러는
    멀쩡했고, 종목 하나를 등록하자 12초 만에 `ok` 로 돌아왔다.
    """
    _fake_poller(monkeypatch, phase="PRE", watching=0, last=None)
    check = _check_poller(datetime.now(timezone.utc))
    assert check.status == "ok"


def test_watching_but_never_received_is_down(monkeypatch):
    """반대쪽도 못 박는다 — 보고 있는데 못 받으면 그건 진짜 고장이다.

    등록되면 폴러가 즉시 깨어나므로, 그러고도 한 번도 못 받았다면 멈춘 것이다.
    """
    _fake_poller(monkeypatch, phase="REGULAR", watching=3, last=None)
    assert _check_poller(datetime.now(timezone.utc)).status == "down"


def test_watching_but_stalled_is_down(monkeypatch):
    """보고 있는데 갱신이 오래 끊기면 down."""
    stale = datetime.now(timezone.utc) - timedelta(seconds=health.POLLER_STALL_SEC + 60)
    _fake_poller(monkeypatch, phase="REGULAR", watching=1, last=stale)
    assert _check_poller(datetime.now(timezone.utc)).status == "down"


def test_fresh_update_is_ok(monkeypatch):
    """정상 경로 — 방금 받았으면 ok."""
    fresh = datetime.now(timezone.utc) - timedelta(seconds=5)
    _fake_poller(monkeypatch, phase="REGULAR", watching=1, last=fresh)
    assert _check_poller(datetime.now(timezone.utc)).status == "ok"


def test_error_is_reported_even_when_quiet(monkeypatch):
    """조용한 것이 정상인 상황에도 **마지막 오류는 숨기지 않는다.**

    허용 IP 문제처럼 밤에도 고칠 수 있는 것들이 여기로 드러난다.
    """
    _fake_poller(monkeypatch, phase="PRE", watching=0, error="403 Forbidden")
    check = _check_poller(datetime.now(timezone.utc))
    assert check.status == "degraded"
    assert "403" in check.detail


# ---------------------------------------------------------------- 확정 종가 수집
#
# 수집은 **평일 13:20 한 번**만 돈다. 그래서 "얼마나 지났나"로 재면 주말마다 반드시
# 운다. 아래 테스트들이 그 함정을 못 박는다 (회귀 2026-09-06).


class _FakeRun:
    def __init__(self, started_at: datetime, error: str | None = None) -> None:
        self.started_at = started_at
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None


def _fake_last_run(monkeypatch, run) -> None:
    monkeypatch.setattr(type(health.scheduler), "last_run", property(lambda self: run))


def _kst(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=health.KST)


def test_weekend_after_friday_run_is_not_an_alarm(monkeypatch):
    """**회귀(2026-09-06).** 금요일에 성공했으면 주말 내내 정상이다.

    예전 기준은 "36시간 지나면 degraded" 였다. 수집이 금요일 13:20 에 돌고 나면
    **토요일 새벽 1시 20분부터 월요일 낮까지 매주 빨간불**이 켜졌다 — 고장이 하나도
    없는데. 배포 서버에서 실제로 그 상태를 보고 잡았다.
    """
    _fake_last_run(monkeypatch, _FakeRun(_kst(2026, 9, 4, 13, 20)))  # 금 13:20
    for now in (_kst(2026, 9, 5, 3), _kst(2026, 9, 6, 1, 41), _kst(2026, 9, 7, 12)):
        assert _check_collection(now).status == "ok", now


def test_missed_weekday_run_is_degraded(monkeypatch):
    """반대쪽 — 평일 예정분을 정말 빠뜨리면 여전히 잡는다.

    금요일에 성공한 뒤 월요일 예정분(13:20)이 유예까지 지나도록 안 돌았다.
    """
    _fake_last_run(monkeypatch, _FakeRun(_kst(2026, 9, 4, 13, 20)))
    check = _check_collection(_kst(2026, 9, 7, 17))  # 월 17:00 — 유예 3시간을 넘겼다
    assert check.status == "degraded"
    assert "09-07 13:20" in check.detail


def test_today_run_is_not_blamed_before_grace_ends(monkeypatch):
    """오늘 예정분은 유예 안에서는 책임을 묻지 않는다.

    수집 자체가 몇 분 걸리고 서버가 마침 재시작 중일 수도 있다. 13:25 에 우는 경보를
    만들면 그것대로 무시하게 된다.
    """
    _fake_last_run(monkeypatch, _FakeRun(_kst(2026, 9, 4, 13, 20)))  # 금요일 것뿐
    assert _check_collection(_kst(2026, 9, 7, 13, 25)).status == "ok"


def test_failed_run_is_degraded_regardless_of_schedule(monkeypatch):
    """방금 돌았어도 **실패했으면** 그건 일정과 무관하게 고장이다."""
    _fake_last_run(monkeypatch, _FakeRun(_kst(2026, 9, 4, 13, 20), error="인증키가 틀렸습니다"))
    check = _check_collection(_kst(2026, 9, 4, 13, 30))
    assert check.status == "degraded"
    assert "인증키" in check.detail


def test_never_run_is_not_an_alarm(monkeypatch):
    """기동 직후에는 기록이 없다. 이걸로 울리면 재시작마다 운다."""
    _fake_last_run(monkeypatch, None)
    assert _check_collection(datetime.now(timezone.utc)).status == "ok"
