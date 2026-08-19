"""장 세션 판정 테스트.

**미국 세션은 한국 시간 자정을 넘어 이어진다.** 정규장 22:30~다음날 05:00, 애프터마켓
05:00~08:50 이다. 그래서 한국 시간 새벽에는 **지금 열려 있는 세션이 "어제" 영업일에
속한다.** 달력의 `today` 만 보면 매일 세 시간 넘게 "장 마감"으로 잘못 판정하고,
그 동안 폴러가 갱신을 멈춰 미국 현재가가 굳는다. 실제로 그렇게 동작하고 있었다.

아래 달력 모양은 2026-08-20 05:30 KST 에 토스에서 실제로 받은 응답이다.
"""

from __future__ import annotations

from datetime import datetime

from app.services.price_poller import LIVE_PHASES, resolve_phase


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _us_day(date: str, day_start: str, pre: str, regular: str, after: str) -> dict:
    """하루치 미국 세션. 시각은 전부 KST 표기다(토스가 그렇게 준다)."""
    return {
        "date": date,
        "dayMarket": {"startTime": f"{day_start}T09:00:00+09:00", "endTime": f"{day_start}T17:00:00+09:00"},
        "preMarket": {"startTime": f"{pre}T17:00:00+09:00", "endTime": f"{pre}T22:30:00+09:00"},
        "regularMarket": {
            "startTime": f"{regular}T22:30:00+09:00",
            "endTime": f"{after}T05:00:00+09:00",
        },
        "afterMarket": {"startTime": f"{after}T05:00:00+09:00", "endTime": f"{after}T08:50:00+09:00"},
    }


US_CALENDAR = {
    "previousBusinessDay": _us_day("2026-08-19", "2026-08-19", "2026-08-19", "2026-08-19", "2026-08-20"),
    "today": _us_day("2026-08-20", "2026-08-20", "2026-08-20", "2026-08-20", "2026-08-21"),
    "nextBusinessDay": _us_day("2026-08-21", "2026-08-21", "2026-08-21", "2026-08-21", "2026-08-22"),
}

KR_CALENDAR = {
    "previousBusinessDay": {
        "date": "2026-08-19",
        "integrated": {
            "preMarket": {"startTime": "2026-08-19T08:00:00+09:00", "endTime": "2026-08-19T09:00:00+09:00"},
            "regularMarket": {"startTime": "2026-08-19T09:00:00+09:00", "endTime": "2026-08-19T15:30:00+09:00"},
            "afterMarket": {"startTime": "2026-08-19T15:40:00+09:00", "endTime": "2026-08-19T20:00:00+09:00"},
        },
    },
    "today": {
        "date": "2026-08-20",
        "integrated": {
            "preMarket": {"startTime": "2026-08-20T08:00:00+09:00", "endTime": "2026-08-20T09:00:00+09:00"},
            "regularMarket": {"startTime": "2026-08-20T09:00:00+09:00", "endTime": "2026-08-20T15:30:00+09:00"},
            "afterMarket": {"startTime": "2026-08-20T15:40:00+09:00", "endTime": "2026-08-20T20:00:00+09:00"},
        },
    },
    "nextBusinessDay": {
        "date": "2026-08-21",
        "integrated": {
            "preMarket": {"startTime": "2026-08-21T08:00:00+09:00", "endTime": "2026-08-21T09:00:00+09:00"},
            "regularMarket": {"startTime": "2026-08-21T09:00:00+09:00", "endTime": "2026-08-21T15:30:00+09:00"},
            "afterMarket": {"startTime": "2026-08-21T15:40:00+09:00", "endTime": "2026-08-21T20:00:00+09:00"},
        },
    },
}


# ---------------------------------------------------------------- 미국 (자정을 넘는 세션)


def test_us_after_hours_past_midnight_is_not_closed():
    """05:30 KST — 전 영업일의 애프터마켓이 진행 중이다.

    이것이 실제로 겪은 버그다. "장 마감"으로 떠서 미국 시장이 국내 시간표를 따르는 것처럼
    보였고, 폴러도 갱신을 멈췄다.
    """
    state = resolve_phase(US_CALENDAR, at("2026-08-20T05:30:00+09:00"), country="US")
    assert state.phase == "AFTER"
    assert state.phase in LIVE_PHASES
    # 진행 중인 세션이 속한 영업일을 쓴다. 달력의 "오늘"(8/20)이 아니다.
    assert state.trade_date == "2026-08-19"


def test_us_regular_session_past_midnight():
    """02:00 KST — 전 영업일 정규장 한복판이다."""
    state = resolve_phase(US_CALENDAR, at("2026-08-20T02:00:00+09:00"), country="US")
    assert state.phase == "REGULAR"
    assert state.trade_date == "2026-08-19"


def test_us_gap_between_after_hours_and_day_market_is_closed():
    """08:50~09:00 — 애프터마켓은 끝났고 데이마켓은 아직이다. 이때는 진짜 마감이다."""
    state = resolve_phase(US_CALENDAR, at("2026-08-20T08:55:00+09:00"), country="US")
    assert state.phase == "CLOSED"
    assert state.next_open == "2026-08-20T09:00:00+09:00"


def test_us_day_market_is_live():
    """토스 데이마켓(09:00~17:00 KST). 실제 체결이 일어나므로 갱신해야 한다."""
    state = resolve_phase(US_CALENDAR, at("2026-08-20T10:00:00+09:00"), country="US")
    assert state.phase == "DAY"
    assert state.phase in LIVE_PHASES


def test_us_next_open_points_at_the_nearest_future_session():
    """마감 중에는 다음에 열리는 세션을 알려 줘야 한다. 그게 '어제' 달력에 있어도 마찬가지다."""
    state = resolve_phase(US_CALENDAR, at("2026-08-20T08:55:00+09:00"), country="US")
    assert state.next_open == "2026-08-20T09:00:00+09:00"


def test_us_session_end_is_reported():
    state = resolve_phase(US_CALENDAR, at("2026-08-20T05:30:00+09:00"), country="US")
    assert state.session_end == "2026-08-20T08:50:00+09:00"


# ---------------------------------------------------------------- 국내


def test_kr_regular_hours():
    state = resolve_phase(KR_CALENDAR, at("2026-08-20T10:00:00+09:00"), country="KR")
    assert state.phase == "REGULAR"
    assert state.trade_date == "2026-08-20"


def test_kr_dawn_is_closed_not_yesterdays_session():
    """국내 세션은 자정을 넘지 않는다. 새벽 5시는 전날 애프터마켓이 아니라 마감이다."""
    state = resolve_phase(KR_CALENDAR, at("2026-08-20T05:00:00+09:00"), country="KR")
    assert state.phase == "CLOSED"
    assert state.next_open == "2026-08-20T08:00:00+09:00"


def test_kr_between_regular_and_after_is_closed():
    """15:30~15:40 은 시간외 단일가 준비 시간이라 어느 세션에도 없다."""
    state = resolve_phase(KR_CALENDAR, at("2026-08-20T15:35:00+09:00"), country="KR")
    assert state.phase == "CLOSED"


def test_kr_holiday_is_flagged():
    """휴장일이면 `integrated` 가 통째로 null 이다. 공휴일표를 우리가 들 필요가 없다.

    실제 사례 — 2026-08-17 은 광복절 대체공휴일이었다. 전 영업일은 8/14(금),
    다음 영업일은 8/18(화)다.
    """
    calendar = {
        "previousBusinessDay": {
            "date": "2026-08-14",
            "integrated": {
                "preMarket": {"startTime": "2026-08-14T08:00:00+09:00", "endTime": "2026-08-14T09:00:00+09:00"},
                "regularMarket": {"startTime": "2026-08-14T09:00:00+09:00", "endTime": "2026-08-14T15:30:00+09:00"},
                "afterMarket": {"startTime": "2026-08-14T15:40:00+09:00", "endTime": "2026-08-14T20:00:00+09:00"},
            },
        },
        "today": {"date": "2026-08-17", "integrated": None},
        "nextBusinessDay": {
            "date": "2026-08-18",
            "integrated": {
                "preMarket": {"startTime": "2026-08-18T08:00:00+09:00", "endTime": "2026-08-18T09:00:00+09:00"},
                "regularMarket": {"startTime": "2026-08-18T09:00:00+09:00", "endTime": "2026-08-18T15:30:00+09:00"},
                "afterMarket": {"startTime": "2026-08-18T15:40:00+09:00", "endTime": "2026-08-18T20:00:00+09:00"},
            },
        },
    }
    state = resolve_phase(calendar, at("2026-08-17T10:00:00+09:00"), country="KR")
    assert state.phase == "HOLIDAY"
    # 휴장이어도 다음 개장은 알려 준다.
    assert state.next_open == "2026-08-18T08:00:00+09:00"


# ---------------------------------------------------------------- 방어


def test_missing_calendar_is_unknown_not_a_crash():
    """토스가 죽어도 화면은 떠야 한다. 모를 때는 모른다고 답한다."""
    assert resolve_phase(None, at("2026-08-20T10:00:00+09:00")).phase == "UNKNOWN"


def test_empty_calendar_does_not_crash():
    state = resolve_phase({}, at("2026-08-20T10:00:00+09:00"), country="US")
    assert state.phase in ("HOLIDAY", "CLOSED", "UNKNOWN")


def test_broken_times_are_skipped():
    """시각 문자열이 깨져 있으면 그 세션만 건너뛴다. 전체가 죽으면 안 된다."""
    calendar = {
        "today": {
            "date": "2026-08-20",
            "dayMarket": {"startTime": "이상한값", "endTime": "2026-08-20T17:00:00+09:00"},
            "regularMarket": {
                "startTime": "2026-08-20T22:30:00+09:00",
                "endTime": "2026-08-21T05:00:00+09:00",
            },
        }
    }
    state = resolve_phase(calendar, at("2026-08-20T23:00:00+09:00"), country="US")
    assert state.phase == "REGULAR"
