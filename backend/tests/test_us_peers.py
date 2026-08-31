"""미국 동종업계 비교 회귀 테스트.

국내(`test_screener.py`)와 지키는 것이 같다. 다른 점만 못 박는다:

1. **SIC 는 그대로 맞춰 묶는다.** 국내 DART 코드는 자릿수가 회사마다 달라 앞 두 자리로
   잘라야 했지만, SEC 의 SIC 는 네 자리로 일정하다. 자르면 오히려 엉뚱한 회사가 섞인다
   (35 로 자르면 컴퓨터·기계·반도체가 한 묶음이 된다).
2. **주가를 못 받은 종목도 목록에 남긴다.** 미국은 KRX 확정 종가 같은 물러설 자리가
   없어 지표가 빌 수 있는데, 그 줄을 빼 버리면 "그 회사가 동종업계에 없다"로 읽힌다.
3. **지표를 아는 종목이 적다.** 회사당 3~4MB 를 받아야 해서 상위 100종목만 담는다.
   화면이 그 수를 밝힐 수 있도록 응답에 담아 보낸다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.base import get_session, init_db
from app.models.us_company import SecCompany, SecFinancial
from app.services import sec_companies, us_universe, valuation
from tests.conftest import run_async


@pytest.fixture(autouse=True)
def _clean():
    init_db()
    with get_session() as session:
        session.query(SecFinancial).delete()
        session.query(SecCompany).delete()
        session.commit()
    if hasattr(sec_companies.get_company, "cache_clear"):
        sec_companies.get_company.cache_clear()


def _add(
    ticker: str,
    *,
    cik: str | None = None,
    sic: str | None = "3674",
    sic_name: str | None = "Semiconductors & Related Devices",
    shares: int | None = 1_000_000,
    income: int | None = 1_000_000_000,
    equity: int | None = 10_000_000_000,
    revenue: int | None = 50_000_000_000,
    prev_revenue: int | None = None,
) -> None:
    cik = cik or ticker.ljust(10, "0")
    with get_session() as session:
        session.add(
            SecCompany(
                ticker=ticker,
                cik=cik,
                name=f"{ticker} Inc.",
                shares_outstanding=shares,
                shares_as_of="2026-07-01",
                sic=sic,
                sic_description=sic_name,
            )
        )
        session.add(
            SecFinancial(
                cik=cik,
                fiscal_year=2025,
                period_end="2025-12-31",
                revenue=revenue,
                net_income=income,
                total_equity=equity,
            )
        )
        if prev_revenue is not None:
            session.add(
                SecFinancial(
                    cik=cik, fiscal_year=2024, period_end="2024-12-31", revenue=prev_revenue
                )
            )
        session.commit()


def _prices(mapping: dict[str, str]) -> None:
    """폴러 캐시에 값을 넣는다. 미국 지표는 이 값이 있어야 계산된다."""
    from decimal import Decimal as D
    from datetime import datetime, timezone

    from app.services.price_poller import CachedPrice, poller

    poller._wanted = {t: 0.0 for t in mapping}
    poller._prices = {
        t: CachedPrice(symbol=t, last_price=D(v), timestamp=None,
                       fetched_at=datetime.now(timezone.utc))
        for t, v in mapping.items()
    }


# ---------------------------------------------------------------- 업종 묶기


def test_sic_is_matched_exactly_not_by_prefix():
    """**국내와 다른 점.** SIC 는 네 자리로 일정해서 자를 필요가 없다.

    앞 두 자리로 자르면 3571(컴퓨터)과 3674(반도체)가 한 묶음이 된다.
    """
    _add("NVDA", sic="3674")
    _add("AMD", sic="3674")
    _add("AAPL", sic="3571", sic_name="Electronic Computers")

    assert set(us_universe.peers("NVDA")) == {"AMD"}
    assert us_universe.peers("AAPL") == []


def test_industry_name_comes_from_sec():
    """국내는 코드만 있어 이름을 못 적었다. 미국은 SEC 가 함께 준다."""
    _add("NVDA")
    code, name = us_universe.industry_of("NVDA")
    assert code == "3674"
    assert name == "Semiconductors & Related Devices"


def test_unknown_industry_gives_no_peers():
    """아무 종목이나 '동종업계'라고 보여주느니 비워 둔다."""
    _add("XYZ", sic=None, sic_name=None)
    _add("NVDA", sic="3674")
    assert us_universe.peers("XYZ") == []


def test_companies_without_shares_are_left_out():
    """발행주식수가 없으면 시가총액을 못 내 정렬도 지표도 안 된다."""
    _add("NVDA", sic="3674")
    _add("GHOST", sic="3674", shares=None)
    assert us_universe.peers("NVDA") == []


# ---------------------------------------------------------------- 지표 계산


def test_metrics_use_the_poller_price():
    """시총 = 주가 × 발행주식수. 주가는 폴러가 들고 있는 것을 쓴다."""
    _add("NVDA", shares=1_000_000, income=1_000_000_000, equity=10_000_000_000)
    _prices({"NVDA": "100000"})  # 시총 = 10만 × 100만 = 1,000억

    row = {r.ticker: r for r in valuation.us_screen_rows(["NVDA"])}["NVDA"]
    assert row.market_cap == Decimal("100000000000")
    assert row.per == Decimal("100.00")  # 1,000억 / 10억
    assert row.pbr == Decimal("10.00")
    assert row.roe == Decimal("10.00")


def test_a_row_without_a_price_still_appears():
    """**회귀 방지.** 주가를 못 받았다고 목록에서 빼면 '동종업계에 없는 회사'로 읽힌다."""
    _add("NVDA")
    _prices({})

    rows = {r.ticker: r for r in valuation.us_screen_rows(["NVDA"])}
    assert "NVDA" in rows
    assert rows["NVDA"].price is None
    assert rows["NVDA"].per is None


def test_loss_making_company_has_no_per():
    _add("INTC", income=-1_000_000_000)
    _prices({"INTC": "100"})
    row = {r.ticker: r for r in valuation.us_screen_rows(["INTC"])}["INTC"]
    assert row.per is None
    assert row.pbr is not None


def test_revenue_growth_needs_the_previous_year():
    _add("NVDA", revenue=60_000_000_000, prev_revenue=50_000_000_000)
    _add("AMD", revenue=60_000_000_000)
    _prices({"NVDA": "100", "AMD": "100"})

    rows = {r.ticker: r for r in valuation.us_screen_rows(["NVDA", "AMD"])}
    assert rows["NVDA"].revenue_growth == Decimal("20.00")
    assert rows["AMD"].revenue_growth is None


def test_companies_without_financials_are_left_out():
    """재무가 없으면 지표를 하나도 못 낸다. 빈 줄을 만들지 않는다."""
    with get_session() as session:
        session.add(SecCompany(ticker="SPY", cik="0000000001", name="SPDR", sic="6726"))
        session.commit()
    assert valuation.us_screen_rows(["SPY"]) == []


def test_no_tickers_gives_nothing():
    assert valuation.us_screen_rows([]) == []


# ---------------------------------------------------------------- 업종을 공짜로 넓히기


def test_industry_is_remembered_when_filings_are_fetched():
    """**유니버스가 훑지 않는 종목도 사용자가 열면 업종을 알게 된다.**

    적재는 거래대금 상위 100종목만 본다. 그 밖의 종목(KO 가 그랬다)은 업종이 빈 채로
    남는데, 공시 목록을 보려면 어차피 같은 응답을 받으므로 그때 챙겨 둔다.
    """
    _add("KO", cik="0000021344", sic=None, sic_name=None)
    us_universe.remember_industry(
        "0000021344", {"sic": "2080", "sicDescription": "Beverages"}
    )
    if hasattr(sec_companies.get_company, "cache_clear"):
        sec_companies.get_company.cache_clear()
    assert us_universe.industry_of("KO") == ("2080", "Beverages")


def test_remembering_does_not_overwrite_what_we_know():
    """이미 아는 업종을 덮지 않는다 — 적재가 넣은 값이 더 믿을 만하다."""
    _add("NVDA", cik="0001045810", sic="3674")
    us_universe.remember_industry("0001045810", {"sic": "9999", "sicDescription": "바뀜"})
    if hasattr(sec_companies.get_company, "cache_clear"):
        sec_companies.get_company.cache_clear()
    assert us_universe.industry_of("NVDA")[0] == "3674"


def test_broken_submissions_do_not_raise():
    """공시 목록은 그대로 나와야 한다. 업종 저장은 곁다리다."""
    us_universe.remember_industry("0000000000", {})
    us_universe.remember_industry("0000000000", {"sic": None})


def test_peers_are_empty_when_the_subject_has_no_metrics(monkeypatch):
    """**회귀 방지(2026-08-25).** 자기 자신이 빠진 비교표는 쓸모가 없다.

    서버에서 KO 를 열었더니 자기는 없고 이름 모를 두 회사만 나왔다 — 유니버스가
    훑지 않은 종목이라 재무가 없었기 때문이다. 무엇과 견주라는 것인지 알 수 없다.

    **SEC 를 부르지 않는다.** 재무를 채우는 부분은 여기서 확인할 것이 아니고,
    테스트가 네트워크를 타면 결과가 그날 사정에 따라 달라진다.
    """
    from app.routers import us_stocks

    async def _no_fetch(*args, **kwargs):
        return 0

    monkeypatch.setattr(us_stocks.sec_financials, "ensure_financials", _no_fetch)

    # 비교 대상은 재무가 없고, 같은 업종의 다른 회사만 갖춰져 있다.
    with get_session() as session:
        session.add(
            SecCompany(ticker="KO", cik="0000021344", name="COCA COLA CO",
                       shares_outstanding=1_000, sic="2080", sic_description="Beverages")
        )
        session.commit()
    _add("PEP", cik="0000077476", sic="2080", sic_name="Beverages")
    if hasattr(sec_companies.get_company, "cache_clear"):
        sec_companies.get_company.cache_clear()

    got = run_async(us_stocks.get_us_peers(ticker="KO", limit=5))
    assert got.rows == []
