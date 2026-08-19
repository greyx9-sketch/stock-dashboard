"""가동 상태 판단 테스트.

여기서 중요한 것은 **오작동하지 않는 것**이다. 멀쩡한데 자꾸 우는 경보는 며칠 만에
무시하게 되고, 그러면 진짜 고장도 같이 묻힌다. 그래서 임계값과 "장 마감에는 조용하다"는
규칙을 못 박아 둔다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import health
from app.services.health import Check, _check_errors, _worst, record_error


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
