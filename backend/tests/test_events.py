"""일정 캘린더 회귀 테스트.

이 기능에서 틀리기 쉬운 것은 **날짜**다. 숫자가 하나 어긋나도 화면은 멀쩡해 보이고,
사람은 캘린더를 믿기 때문에 알아채지 못한다. 그래서 여기서는 두 가지를 못 박는다:

1. **만기일 계산이 달력과 맞는가.** 규칙("각 결제월의 두 번째 목요일")을 코드로 옮기면서
   한 주를 더하거나 빼기 쉽다. 파이썬 표준 달력으로 독립적으로 다시 구해 대조한다.
2. **원문에서 옮겨 적은 회의 일정이 그대로 나오는가.** 씨앗 파일을 고치다 날짜를
   흘리면 캘린더에서 회의가 통째로 사라진다.

옮겨 적은 값 자체가 맞는지는 테스트가 증명할 수 없다 — 그건 사람이 원문을 열어 봐야
한다. 그래서 씨앗 파일에 출처 URL 과 확인일을 함께 적어 두었다.
"""

from __future__ import annotations

import calendar
from datetime import date

import pytest

from app.models.base import init_db
from app.services import events as events_service
from app.services.events import CalendarEvent, month_range, option_expiry


@pytest.fixture(autouse=True)
def _db():
    """직접 입력 일정은 DB 를 쓴다. 테스트용 임시 DB 에 표를 만들어 둔다."""
    init_db()


# ---------------------------------------------------------------- 만기일


def test_expiry_is_the_second_thursday_every_month():
    """**규칙을 코드로 옮기다 한 주 어긋나기 쉽다.** 24개월을 달력과 대조한다."""
    for year in (2026, 2027):
        for month in range(1, 13):
            thursdays = [
                day
                for day in range(1, calendar.monthrange(year, month)[1] + 1)
                if date(year, month, day).weekday() == 3
            ]
            assert option_expiry(year, month) == date(year, month, thursdays[1])


def test_expiry_when_the_first_day_is_thursday():
    """1일이 목요일이면 첫 목요일이 1일이고 두 번째는 8일이다. 경계라 따로 본다."""
    assert date(2026, 1, 1).weekday() == 3
    assert option_expiry(2026, 1) == date(2026, 1, 8)


def test_expiry_when_the_first_day_is_friday():
    """1일이 금요일이면 첫 목요일이 7일로 밀린다 — 두 번째는 14일."""
    assert date(2027, 1, 1).weekday() == 4
    assert option_expiry(2027, 1) == date(2027, 1, 14)


def test_every_month_has_an_expiry():
    """달마다 하나씩 있어야 한다. 빠진 달이 있으면 그 달만 조용히 비어 보인다."""
    begin, end = date(2026, 1, 1), date(2026, 12, 31)
    expiries = [e for e in events_service.load(begin, end) if e.kind == "만기"]
    assert len(expiries) == 12
    assert sorted({e.event_date.month for e in expiries}) == list(range(1, 13))


# ---------------------------------------------------------------- 공표된 회의


def test_policy_meetings_come_from_the_seed_file():
    """한국은행이 공표한 2026년 통화정책방향 결정회의 8회가 그대로 나와야 한다."""
    begin, end = date(2026, 1, 1), date(2026, 12, 31)
    found = sorted(e.event_date for e in events_service.load(begin, end) if e.kind == "금통위")
    assert found == [
        date(2026, 1, 15),
        date(2026, 2, 26),
        date(2026, 4, 10),
        date(2026, 5, 28),
        date(2026, 7, 16),
        date(2026, 8, 27),
        date(2026, 10, 22),
        date(2026, 11, 26),
    ]


def test_fomc_meets_eight_times_a_year():
    """연준은 정례회의를 연 8회 연다. 씨앗 파일을 고치다 흘리면 여기서 걸린다."""
    for year in (2026, 2027):
        begin, end = date(year, 1, 1), date(year, 12, 31)
        fomc = [e for e in events_service.load(begin, end) if e.kind == "FOMC"]
        assert len(fomc) == 8, f"{year}년 FOMC 가 {len(fomc)}회다"


def test_fomc_warns_about_the_time_difference():
    """미국 동부 오후 발표라 한국시간으로는 다음날 새벽이다.

    날짜를 옮기지 않고 밝히기로 했으므로, 그 안내가 빠지면 하루를 착각하게 된다.
    """
    begin, end = date(2026, 12, 1), date(2026, 12, 31)
    fomc = next(e for e in events_service.load(begin, end) if e.kind == "FOMC")
    assert "다음날 새벽" in (fomc.memo or "")


def test_projection_meetings_are_marked():
    """경제전망(SEP)이 함께 나오는 회의는 시장 반응이 다르다. 제목에서 갈린다."""
    begin, end = date(2026, 1, 1), date(2026, 12, 31)
    fomc = [e for e in events_service.load(begin, end) if e.kind == "FOMC"]
    with_sep = [e for e in fomc if "SEP" in e.title]
    assert len(with_sep) == 4  # 3·6·9·12월


def test_automatic_events_are_not_editable():
    """**공표된 값을 사람이 고칠 수 있으면 안 된다.** 고치는 순간 출처와 어긋난다."""
    begin, end = date(2026, 1, 1), date(2026, 12, 31)
    for event in events_service.load(begin, end):
        if event.kind in ("금통위", "FOMC", "만기"):
            assert event.editable is False
            assert event.source, f"{event.kind} 에 출처가 없다"


# ---------------------------------------------------------------- 직접 입력


def test_added_event_shows_up_and_is_editable():
    new_id = events_service.add(
        event_date=date(2026, 9, 3),
        kind="실적",
        title="삼성전자 3분기 잠정실적",
        symbol="005930",
        memo=None,
    )
    begin, end = month_range(2026, 9)
    mine = [e for e in events_service.load(begin, end) if e.editable]
    assert [e.title for e in mine] == ["삼성전자 3분기 잠정실적"]
    assert mine[0].id == new_id
    assert mine[0].symbol == "005930"


def test_blank_symbol_becomes_none():
    """빈 문자열을 그대로 두면 화면에 빈 줄이 하나 생긴다."""
    events_service.add(
        event_date=date(2026, 9, 4), kind="기타", title="점검", symbol="   ", memo="  "
    )
    begin, end = month_range(2026, 9)
    added = next(e for e in events_service.load(begin, end) if e.title == "점검")
    assert added.symbol is None
    assert added.memo is None


def test_removing_twice_is_not_an_error():
    """지우기를 두 번 눌러도 오류로 만들지 않는다. 이미 없으면 거짓만 돌려준다."""
    new_id = events_service.add(
        event_date=date(2026, 9, 5), kind="기타", title="지울 것", symbol=None, memo=None
    )
    assert events_service.remove(new_id) is True
    assert events_service.remove(new_id) is False


def test_events_come_back_in_date_order():
    """화면이 그대로 그리는 순서다. 뒤섞이면 목록이 읽히지 않는다."""
    events_service.add(
        event_date=date(2026, 10, 30), kind="기타", title="늦은 것", symbol=None, memo=None
    )
    events_service.add(
        event_date=date(2026, 10, 2), kind="기타", title="이른 것", symbol=None, memo=None
    )
    begin, end = month_range(2026, 10)
    dates = [e.event_date for e in events_service.load(begin, end)]
    assert dates == sorted(dates)


def test_automatic_events_sort_before_typed_ones_on_the_same_day():
    """같은 날이면 직접 적은 것이 아래로 모여야 찾기 쉽다."""
    expiry = option_expiry(2026, 10)
    events_service.add(
        event_date=expiry, kind="기타", title="내가 적은 것", symbol=None, memo=None
    )
    begin, end = month_range(2026, 10)
    same_day = [e for e in events_service.load(begin, end) if e.event_date == expiry]
    assert [e.editable for e in same_day] == [False, True]


# ---------------------------------------------------------------- 기간 자르기


def test_month_range_covers_the_whole_month():
    assert month_range(2026, 2) == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_range(2028, 2) == (date(2028, 2, 1), date(2028, 2, 29))  # 윤년


def test_events_outside_the_month_are_left_out():
    """11월을 열었는데 12월 FOMC 가 끼어 있으면 안 된다."""
    begin, end = month_range(2026, 11)
    for event in events_service.load(begin, end):
        assert begin <= event.event_date <= end


def test_calendar_event_carries_where_it_came_from():
    """이 프로젝트는 출처 없는 숫자를 화면에 두지 않는다. 일정도 같다."""
    fields = CalendarEvent.__dataclass_fields__
    assert "source" in fields and "source_url" in fields


# ---------------------------------------------------------------- 다가오는 일정 띠


def _upcoming(**kwargs):
    from app.routers.events import get_upcoming

    return get_upcoming(**{"days": 60, "limit": 4, **kwargs})


def test_upcoming_counts_the_days_on_the_server():
    """**날짜 계산을 서버가 한다.**

    브라우저에서 빼면 시간대가 다를 때 하루 어긋난다 — 한국 새벽에는 서버(UTC)가 아직
    어제라, 같은 일정이 D-2 로도 D-3 으로도 보인다.
    """
    from datetime import date, timedelta

    target = date.today() + timedelta(days=3)
    events_service.add(
        event_date=target, kind="실적", title="사흘 뒤 실적", symbol=None, memo=None
    )
    found = {u.event.title: u.days_away for u in _upcoming(limit=20)}
    assert found["사흘 뒤 실적"] == 3


def test_today_is_included():
    """**오늘이 금통위인데 빠지면** 그날 아침에 가장 필요한 정보가 사라진다."""
    from datetime import date

    events_service.add(
        event_date=date.today(), kind="기타", title="오늘 일정", symbol=None, memo=None
    )
    found = {u.event.title: u.days_away for u in _upcoming(limit=20)}
    assert found["오늘 일정"] == 0


def test_past_events_are_left_out():
    """지난 일정은 '다가오는' 것이 아니다."""
    from datetime import date, timedelta

    events_service.add(
        event_date=date.today() - timedelta(days=1), kind="기타", title="어제 일정",
        symbol=None, memo=None,
    )
    assert "어제 일정" not in {u.event.title for u in _upcoming(limit=20)}


def test_upcoming_is_limited_and_sorted():
    """가까운 것부터 몇 건만. 띠 한 줄에 들어가야 한다."""
    from datetime import date, timedelta

    for offset in (9, 5, 7):
        events_service.add(
            event_date=date.today() + timedelta(days=offset), kind="기타",
            title=f"{offset}일 뒤", symbol=None, memo=None,
        )
    got = _upcoming(days=10, limit=2)
    assert len(got) == 2
    assert [u.days_away for u in got] == sorted(u.days_away for u in got)


def test_far_future_is_cut_off():
    """1년 뒤 FOMC 가 '다가오는 일정'에 뜨면 띠가 뜻을 잃는다."""
    from datetime import date, timedelta

    events_service.add(
        event_date=date.today() + timedelta(days=200), kind="기타", title="먼 일정",
        symbol=None, memo=None,
    )
    assert "먼 일정" not in {u.event.title for u in _upcoming(days=30, limit=20)}
