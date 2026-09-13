"""메모 회고 테스트 — 그 메모를 쓴 뒤 얼마나 올랐나.

**틀려도 그럴듯해 보이는 종류의 숫자다.** "+18.4%" 는 어디에 갖다 놔도 수익률처럼
보이므로, 기준일이 하루 밀렸거나 지수만 최신 값을 썼어도 눈으로는 잡히지 않는다.
그래서 여기서는 값이 나오는지가 아니라 **무엇과 무엇을 뺐는지**를 못 박는다.

특히 셋:

  1. 휴장일에 쓴 메모는 **직전 거래일** 종가를 기준으로 잡는가.
  2. 메모 날짜를 **한국 날짜**로 세는가 — 저장은 UTC 다. 한국시간 자정~아침 9시에 쓴
     메모가 하루 뒤로 밀리면 기준가가 통째로 어제 것이 된다(`app/clock.py` 와 같은 함정).
  3. 지수를 종목과 **같은 두 거래일**로 재는가. 지수만 오늘 값을 쓰면 국내 장중에
     하루치가 지수 쪽에만 더해져 알파가 늘 마이너스로 기운다.

네트워크는 부르지 않는다. 토스 자리에 가짜를 끼운다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.clock import today_kst
from app.models.base import get_session, init_db
from app.models.quote import KrxDailyQuote
from app.services import note_return
from app.services import notes as note_service
from app.services.note_return import Point, Series, _note_date, _stopped

from tests.conftest import run_async

KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------- 가짜 토스


class FakeToss:
    """캔들만 돌려주는 가짜. `pages` 는 심볼 → 최신순 캔들 목록이다.

    페이지네이션도 흉내 낸다 — 한 번에 `page_size` 봉씩 끊어 주고 `nextBefore` 를 함께
    돌려준다. `before` 는 inclusive 라 경계의 봉이 한 번 더 온다. 실제 API 가 그렇고,
    그 겹침을 중복으로 세지 않는지가 확인할 거리다.
    """

    def __init__(self, pages: dict[str, list[dict]], page_size: int = 200) -> None:
        self.pages = pages
        self.page_size = page_size
        self.calls: list[tuple[str, str | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _page(self, symbol, before):
        self.calls.append((symbol, before))
        candles = self.pages.get(symbol)
        if candles is None:
            raise note_return.TossError("종목을 찾을 수 없습니다.")
        if before:
            candles = [c for c in candles if c["timestamp"] <= before]
        page = candles[: self.page_size]
        rest = candles[self.page_size :]
        return page, (rest[0]["timestamp"] if rest else None)

    async def get_candle_page(self, symbol, *, interval="1d", count=100, before=None):
        return self._page(symbol, before)

    async def get_indicator_candle_page(self, symbol, *, interval="1d", count=100, before=None):
        return self._page(symbol, before)


def candles(*pairs: tuple[str, str]) -> list[dict]:
    """(거래일, 종가) 를 토스 캔들 모양으로. 실제 응답처럼 **최신순**으로 세운다."""
    rows = [
        {"timestamp": f"{day}T09:00:00.000+09:00", "closePrice": close} for day, close in pairs
    ]
    return sorted(rows, key=lambda c: c["timestamp"], reverse=True)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    """메모·시세·캐시를 매번 비운다. 캐시가 남으면 다음 테스트가 남의 답을 본다."""
    init_db()
    for note in note_service.list_notes(limit=note_service.MAX_LIMIT):
        note_service.remove(note.id)
    with get_session() as session:
        session.query(KrxDailyQuote).delete()
        session.commit()
    note_return._series_cache.clear()
    yield
    note_return._series_cache.clear()


def write(symbol: str, day: str, hour: int = 12) -> int:
    """그 날(한국시각) 그 시각에 쓴 메모를 심는다. 저장은 UTC 로 간다."""
    when = datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=KST)
    note = note_service.create(symbol, f"{symbol} {day} 메모")
    with get_session() as session:
        row = session.get(note_service.Note, note.id)
        row.created_at = when.astimezone(timezone.utc)
        row.updated_at = row.created_at
        session.commit()
    return note.id


def krx(symbol: str, market: str, *pairs: tuple[str, int]) -> None:
    with get_session() as session:
        for day, close in pairs:
            session.add(
                KrxDailyQuote(
                    trade_date=day,
                    symbol=symbol,
                    isin="",
                    name=symbol,
                    market=market,
                    close=close,
                    change=0,
                    change_rate=0,
                    open=close,
                    high=close,
                    low=close,
                    volume=0,
                    trade_value=0,
                    listed_shares=0,
                    market_cap=0,
                )
            )
        session.commit()


def retro(monkeypatch, fake: FakeToss):
    monkeypatch.setattr(note_return, "TossClient", lambda: fake)
    items, error = run_async(note_return.note_returns(note_service.list_notes(limit=50)))
    return {i.note_id: i for i in items}, error


# ---------------------------------------------------------------- 날짜 고르기


def test_holiday_note_falls_back_to_the_previous_session():
    """휴장일에 쓴 메모. 그 날짜의 종가는 없으므로 직전 거래일 종가를 쓴다."""
    series = Series([Point("2026-08-13", Decimal("100")), Point("2026-08-14", Decimal("110"))])
    # 8/15 는 광복절, 8/16 은 일요일이다.
    assert series.on_or_before("2026-08-16").date == "2026-08-14"
    assert series.on_or_before("2026-08-14").date == "2026-08-14"


def test_note_written_before_listing_has_no_base():
    """상장 전에 쓴 메모에는 기준가가 없다. 0원으로 나누지 않고 그냥 비운다."""
    series = Series([Point("2026-08-14", Decimal("110"))])
    assert series.on_or_before("2026-07-01") is None


def test_note_date_is_counted_in_korea():
    """저장은 UTC 다. 한국시간 **자정~아침 9시**에 쓴 메모가 하루 뒤로 밀리면 안 된다.

    `app/clock.py` 가 막은 것과 같은 함정이다. 여기서 밀리면 기준가가 통째로 어제 것이 된다.
    """

    class FakeNote:
        id = 1
        symbol = "005930"
        created_at = "2026-09-13T22:30:00+00:00"  # = 한국시간 9/14 07:30

    assert _note_date(FakeNote()) == "2026-09-14"


def test_stopped_symbol_is_detected():
    """마지막 종가가 시장보다 한참 뒤처져 있으면 거래가 멈춘 것이다."""
    assert _stopped("2026-06-01", "2026-09-01") is True
    assert _stopped("2026-08-28", "2026-09-01") is False  # 연휴가 붙어도 이 정도는 정상


# ---------------------------------------------------------------- 국내: DB 확정 종가


def test_kr_uses_krx_closes_and_beats_the_index(monkeypatch):
    """국내 종목은 KRX 확정 종가를 쓴다 — 관심종목·현재가 화면과 같은 숫자라야 한다.

    토스는 **지수를 받으러만** 나간다. 종목 캔들까지 부르면 호출도 늘고, 한 화면 안에서
    출처가 다른 두 종가가 섞인다(services/watchlist.py 의 표 참고).
    """
    krx("005930", "KOSPI", ("2026-08-14", 100_000), ("2026-09-01", 110_000))
    note = write("005930", "2026-08-16")
    fake = FakeToss({"KOSPI": candles(("2026-08-14", "3000"), ("2026-09-01", "3060"))})

    items, error = retro(monkeypatch, fake)

    got = items[note]
    assert error is None
    assert (got.base_date, got.as_of) == ("2026-08-14", "2026-09-01")
    assert got.change_rate == pytest.approx(10.0)
    assert (got.index_label, got.index_rate) == ("코스피", pytest.approx(2.0))
    # 종목 캔들은 부르지 않았다 — 국내 종가는 DB 에 있다.
    assert [c[0] for c in fake.calls] == ["KOSPI"]


def test_kosdaq_note_is_compared_to_kosdaq(monkeypatch):
    """코스닥 종목을 코스피와 견주면 알파가 통째로 틀어진다. 두 지수의 움직임이 다르다."""
    krx("247540", "KOSDAQ", ("2026-08-14", 100), ("2026-09-01", 100))
    note = write("247540", "2026-08-14")
    fake = FakeToss(
        {
            "KOSDAQ": candles(("2026-08-14", "900"), ("2026-09-01", "855")),
            "KOSPI": candles(("2026-08-14", "3000"), ("2026-09-01", "3300")),
        }
    )

    items, _ = retro(monkeypatch, fake)

    assert items[note].index_label == "코스닥"
    assert items[note].index_rate == pytest.approx(-5.0)


def test_index_is_measured_over_the_same_two_days(monkeypatch):
    """**지수만 최신 값을 쓰면 안 된다.**

    국내 확정 종가는 장중에 어제까지만 있는데 지수 캔들에는 오늘 봉이 이미 있다.
    짝을 안 맞추면 그 하루치가 지수 쪽에만 더해져 알파가 늘 마이너스로 기운다.
    """
    krx("005930", "KOSPI", ("2026-08-14", 100_000), ("2026-09-01", 110_000))
    note = write("005930", "2026-08-14")
    fake = FakeToss(
        {
            # 지수에는 종목보다 하루 더 최신인 봉(9/02)이 있다.
            "KOSPI": candles(
                ("2026-08-14", "3000"), ("2026-09-01", "3060"), ("2026-09-02", "3300")
            )
        }
    )

    items, _ = retro(monkeypatch, fake)

    # 9/02 의 +10% 가 아니라 9/01 까지의 +2% 라야 종목과 같은 기간이다.
    assert items[note].index_rate == pytest.approx(2.0)


def test_stopped_stock_is_left_out(monkeypatch):
    """거래정지·상장폐지 종목의 낡은 종가로 수익률을 내보내면 지금도 그런 줄 안다."""
    krx("005930", "KOSPI", ("2026-09-01", 110_000))  # 시장의 마지막 거래일
    krx("900100", "KOSPI", ("2026-06-01", 5_000), ("2026-06-02", 2_500))
    live = write("005930", "2026-09-01")
    dead = write("900100", "2026-06-01")
    fake = FakeToss({"KOSPI": candles(("2026-06-01", "3000"), ("2026-09-01", "3060"))})

    items, _ = retro(monkeypatch, fake)

    assert dead not in items
    assert live in items


# ---------------------------------------------------------------- 미국: 토스 일봉


def test_us_note_return(monkeypatch):
    note = write("AAPL", "2026-07-31")
    fake = FakeToss(
        {
            "AAPL": candles(("2026-07-31", "300"), ("2026-09-11", "330")),
            "SPY": candles(("2026-07-31", "700"), ("2026-09-11", "714")),
        }
    )

    items, _ = retro(monkeypatch, fake)

    got = items[note]
    assert got.change_rate == pytest.approx(10.0)
    assert (got.index_label, got.index_rate) == ("S&P500", pytest.approx(2.0))


def test_same_symbol_is_fetched_once(monkeypatch):
    """한 종목에 메모가 여럿 달린다. 메모마다 캔들을 받으면 호출이 그만큼 늘어난다."""
    for day in ("2026-07-31", "2026-08-10", "2026-08-20"):
        write("AAPL", day)
    fake = FakeToss(
        {
            "AAPL": candles(("2026-07-31", "300"), ("2026-08-10", "310"), ("2026-09-11", "330")),
            "SPY": candles(("2026-07-31", "700"), ("2026-09-11", "714")),
        }
    )

    items, _ = retro(monkeypatch, fake)

    assert len(items) == 3
    assert [c[0] for c in fake.calls].count("AAPL") == 1


def test_pages_are_followed_until_the_oldest_note(monkeypatch):
    """한 번에 200봉이라 그보다 먼 과거는 이어 받아야 한다.

    `before` 가 inclusive 라 경계의 봉이 한 번 더 온다. 그것을 중복으로 세면 시리즈가
    지저분해지고, 안 이어 받으면 오래된 메모가 통째로 빠진다.
    """
    # 오늘까지 이어지는 날짜라야 한다. 마지막 봉이 한참 과거면 거래가 멈춘 종목으로
    # 걸러지기 때문이다(`_stopped`). 고정 날짜로 적으면 시간이 지나 저절로 깨진다.
    last = today_kst()
    days = [(last - timedelta(days=n)).isoformat() for n in range(83, -1, -1)]
    note = write("AAPL", days[0])
    fake = FakeToss(
        {
            "AAPL": candles(*((d, "100" if d == days[0] else "110") for d in days)),
            "SPY": candles(*((d, "700") for d in days)),
        },
        page_size=30,  # 실제 200 대신 작게 잡아 페이지가 여러 장 나오게 한다
    )

    items, _ = retro(monkeypatch, fake)

    assert items[note].base_date == days[0]
    assert items[note].change_rate == pytest.approx(10.0)
    assert [c[0] for c in fake.calls].count("AAPL") > 1


def test_missing_symbol_is_skipped_not_fatal(monkeypatch):
    """없는 종목 하나 때문에 나머지 메모의 회고가 사라지면 안 된다."""
    krx("005930", "KOSPI", ("2026-08-14", 100_000), ("2026-09-01", 110_000))
    kr = write("005930", "2026-08-14")
    gone = write("ZZZZ", "2026-08-14")
    fake = FakeToss(
        {
            "KOSPI": candles(("2026-08-14", "3000"), ("2026-09-01", "3060")),
            "SPY": candles(("2026-08-14", "700"), ("2026-09-01", "714")),
        }
    )

    items, error = retro(monkeypatch, fake)

    assert kr in items and gone not in items
    assert error is None  # 종목 하나가 없는 것은 화면 전체의 실패가 아니다


def test_note_written_today_has_no_elapsed_days(monkeypatch):
    """오늘 쓴 메모는 기준일과 비교일이 같다. 화면은 `days` 로 그 조각을 감춘다."""
    krx("005930", "KOSPI", ("2026-09-01", 110_000))
    note = write("005930", "2026-09-01")
    fake = FakeToss({"KOSPI": candles(("2026-09-01", "3060"))})

    items, _ = retro(monkeypatch, fake)

    assert items[note].days == 0
    assert items[note].change_rate == pytest.approx(0.0)
