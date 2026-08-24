"""스크리너·동종업계 비교 회귀 테스트.

스크리너에서 조용히 틀리기 쉬운 것은 **값이 없는 종목을 어떻게 다루느냐**다. 화면에는
그럴듯한 목록이 나오는데 그 안에 있으면 안 되는 종목이 섞여 있어도 알아채기 어렵다.

셋을 못 박는다:

1. **조건을 건 항목의 값이 없으면 뺀다.** 적자라 PER 이 없는 회사가 "PER 15 이하"에
   들어오면 조건이 뜻을 잃는다.
2. **정렬할 때 값 없는 줄은 뒤로 보낸다.** None 을 0 으로 치면 적자 기업이 'PER 낮은
   순' 맨 앞에 올라온다. 싼 것이 아니라 낼 수 없는 것이다.
3. **업종은 앞 2자리로 묶는다.** DART 가 주는 코드의 자릿수가 회사마다 달라(삼성전자
   `264` / SK하이닉스 `2612`) 완전 일치로는 같은 업종이 영영 안 묶인다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.base import get_session, init_db
from app.models.corp import DartCorp
from app.models.dividend import DartDividend
from app.models.financial import DartFinancial
from app.models.quote import KrxDailyQuote
from app.services import universe, valuation

TRADE_DATE = "2026-08-21"


@pytest.fixture(autouse=True)
def _clean():
    init_db()
    with get_session() as session:
        session.query(KrxDailyQuote).delete()
        session.query(DartFinancial).delete()
        session.query(DartDividend).delete()
        session.query(DartCorp).delete()
        session.commit()
    # 종목코드→고유번호 조회에 캐시가 있으면 테스트끼리 샌다.
    from app.services import dart_corps

    if hasattr(dart_corps.get_corp, "cache_clear"):
        dart_corps.get_corp.cache_clear()


def _add(
    symbol: str,
    name: str,
    *,
    close: int = 10_000,
    shares: int = 1_000_000,
    income: int | None = 1_000_000_000,
    equity: int | None = 10_000_000_000,
    revenue: int | None = 100_000_000_000,
    prev_revenue: int | None = None,
    dps: int | None = None,
    induty: str | None = None,
    market: str = "KOSPI",
) -> None:
    """한 종목을 통째로 만들어 넣는다. 시세·재무·배당·업종이 다 있어야 표에 나온다."""
    corp_code = symbol.rjust(8, "0")
    with get_session() as session:
        session.add(
            KrxDailyQuote(
                trade_date=TRADE_DATE,
                symbol=symbol,
                isin=f"KR{symbol}",
                name=name,
                market=market,
                close=close,
                change=0,
                change_rate=0,
                open=close,
                high=close,
                low=close,
                volume=1,
                trade_value=1,
                listed_shares=shares,
                market_cap=close * shares,
            )
        )
        session.add(
            DartCorp(
                stock_code=symbol,
                corp_code=corp_code,
                corp_name=name,
                modify_date="20260101",
                induty_code=induty,
            )
        )
        session.add(
            DartFinancial(
                corp_code=corp_code,
                fiscal_year=2025,
                fs_div="CFS",
                revenue=revenue,
                net_income_owners=income,
                total_equity_owners=equity,
                receipt_no="20260310000001",
                extract_version=2,
            )
        )
        if prev_revenue is not None:
            session.add(
                DartFinancial(
                    corp_code=corp_code,
                    fiscal_year=2024,
                    fs_div="CFS",
                    revenue=prev_revenue,
                    receipt_no="20250310000001",
                    extract_version=2,
                )
            )
        if dps is not None:
            session.add(
                DartDividend(corp_code=corp_code, fiscal_year=2025, dps_common=dps, receipt_no="x")
            )
        session.commit()


def _by_symbol(rows) -> dict:
    return {r.symbol: r for r in rows}


# ---------------------------------------------------------------- 지표 계산


def test_metrics_are_computed_from_the_owners_share():
    """상세 화면과 같은 기준이어야 한다 — 목록과 상세의 PER 이 다르면 못 쓴다."""
    # 시총 = 1만원 × 100만주 = 100억. 순이익 10억 → PER 10, 자본 100억 → PBR 1.
    _add("005930", "삼성전자", close=10_000, shares=1_000_000,
         income=1_000_000_000, equity=10_000_000_000)
    row = _by_symbol(valuation.screen_rows())["005930"]
    assert row.per == Decimal("10.00")
    assert row.pbr == Decimal("1.00")
    assert row.roe == Decimal("10.00")


def test_loss_making_company_has_no_per_but_still_appears():
    """적자라고 목록에서 지우지 않는다. PER 칸만 비운다 — 다른 지표는 볼 값어치가 있다."""
    _add("000001", "적자회사", income=-5_000_000_000)
    row = _by_symbol(valuation.screen_rows())["000001"]
    assert row.per is None
    assert row.pbr is not None


def test_revenue_growth_needs_the_previous_year():
    _add("000002", "성장회사", revenue=120_000_000_000, prev_revenue=100_000_000_000)
    _add("000003", "전년없음", revenue=120_000_000_000)
    rows = _by_symbol(valuation.screen_rows())
    assert rows["000002"].revenue_growth == Decimal("20.00")
    assert rows["000003"].revenue_growth is None


def test_stocks_without_financials_are_left_out():
    """재무가 없으면 지표를 낼 수 없다. 빈 줄을 만들지 않는다."""
    with get_session() as session:
        session.add(
            KrxDailyQuote(
                trade_date=TRADE_DATE, symbol="999999", isin="X", name="재무없음",
                market="KOSPI", close=1000, change=0, change_rate=0, open=1000,
                high=1000, low=1000, volume=1, trade_value=1,
                listed_shares=1000, market_cap=1_000_000,
            )
        )
        session.commit()
    assert "999999" not in _by_symbol(valuation.screen_rows())


# ---------------------------------------------------------------- 조건 걸기


def _screen(**kwargs):
    from app.routers.screener import screen

    return screen(**kwargs)


def test_missing_value_fails_the_condition():
    """**회귀 방지.** 적자 회사가 'PER 15 이하'에 들어오면 조건이 뜻을 잃는다."""
    _add("000001", "흑자", close=10_000, income=1_000_000_000)  # PER 10
    _add("000002", "적자", income=-1_000_000_000)  # PER 없음

    got = _screen(per_max=15, pbr_max=None, roe_min=None, yield_min=None, growth_min=None,
                  market=None, sort="per", desc=False, limit=50)
    assert [r.symbol for r in got.rows] == ["000001"]


def test_no_conditions_returns_everything():
    """빈 화면에서 시작하지 않는다. 조건이 없으면 유니버스 전체다."""
    _add("000001", "가")
    _add("000002", "나")
    got = _screen(per_max=None, pbr_max=None, roe_min=None, yield_min=None, growth_min=None,
                  market=None, sort="market_cap", desc=True, limit=50)
    assert got.matched == 2


def test_universe_count_is_reported_separately_from_matches():
    """'조건에 맞는 종목 1개'와 '아는 2개 중 1개'는 다른 말이다."""
    _add("000001", "가", close=10_000, income=1_000_000_000)
    _add("000002", "나", income=-1)
    got = _screen(per_max=15, pbr_max=None, roe_min=None, yield_min=None, growth_min=None,
                  market=None, sort="per", desc=False, limit=50)
    assert got.matched == 1
    assert got.universe == 2


def test_market_filter():
    _add("000001", "코스피", market="KOSPI")
    _add("000002", "코스닥", market="KOSDAQ")
    got = _screen(per_max=None, pbr_max=None, roe_min=None, yield_min=None, growth_min=None,
                  market="KOSDAQ", sort="market_cap", desc=True, limit=50)
    assert [r.symbol for r in got.rows] == ["000002"]


def test_dividend_condition_uses_the_computed_yield():
    _add("000001", "고배당", close=10_000, dps=500)  # 5%
    _add("000002", "저배당", close=10_000, dps=100)  # 1%
    got = _screen(per_max=None, pbr_max=None, roe_min=None, yield_min=3, growth_min=None,
                  market=None, sort="dividend_yield", desc=True, limit=50)
    assert [r.symbol for r in got.rows] == ["000001"]


# ---------------------------------------------------------------- 정렬


def test_rows_without_a_value_sort_last():
    """**회귀 방지.** None 을 0 으로 치면 적자 기업이 'PER 낮은 순' 맨 앞에 온다."""
    _add("000001", "적자", income=-1)
    _add("000002", "흑자", close=10_000, income=1_000_000_000)
    got = _screen(per_max=None, pbr_max=None, roe_min=None, yield_min=None, growth_min=None,
                  market=None, sort="per", desc=False, limit=50)
    assert [r.symbol for r in got.rows] == ["000002", "000001"]


def test_unknown_sort_key_is_rejected():
    from fastapi import HTTPException

    _add("000001", "가")
    with pytest.raises(HTTPException) as caught:
        _screen(per_max=None, pbr_max=None, roe_min=None, yield_min=None, growth_min=None,
                market=None, sort="drop table", desc=True, limit=50)
    assert caught.value.status_code == 422


# ---------------------------------------------------------------- 동종업계


def test_industries_group_by_the_first_two_digits():
    """**회귀 방지.** DART 코드 자릿수가 회사마다 다르다.

    삼성전자 `264` 와 SK하이닉스 `2612` 는 완전 일치로는 영영 안 묶인다.
    """
    _add("005930", "삼성전자", induty="264")
    _add("000660", "SK하이닉스", induty="2612", close=20_000)
    _add("035720", "카카오", induty="63120")

    assert universe.industry_group("005930") == "26"
    assert set(universe.peers("005930")) == {"000660"}
    assert universe.peers("035720") == []


def test_peers_are_empty_when_the_industry_is_unknown():
    """아무 종목이나 '동종업계'라고 보여주느니 비워 둔다."""
    _add("000001", "업종모름", induty=None)
    _add("000002", "다른회사", induty="264")
    assert universe.peers("000001") == []


def test_holding_companies_are_flagged():
    """지주회사는 사업이 달라도 같은 분류다. 감추지 않고 화면이 밝히게 표시한다."""
    _add("105560", "KB금융", induty="64992")
    _add("034730", "SK", induty="64992")
    assert universe.is_holding_company("105560") is True
    assert set(universe.peers("105560")) == {"034730"}

    _add("005930", "삼성전자", induty="264")
    assert universe.is_holding_company("005930") is False


def test_peer_response_puts_the_stock_first():
    """비교 표에서 '나'가 맨 위에 있어야 견주기 쉽다."""
    from app.routers.screener import peers as peers_route

    _add("005930", "삼성전자", induty="264", close=10_000, shares=1_000)
    _add("066570", "LG전자", induty="264", close=10_000, shares=1_000_000)  # 시총이 훨씬 크다

    got = peers_route(symbol="005930", limit=10)
    assert [r.symbol for r in got.rows] == ["005930", "066570"]
    assert got.industry_code == "26"


def test_peer_response_is_empty_without_a_group():
    from app.routers.screener import peers as peers_route

    _add("000001", "업종모름", induty=None)
    got = peers_route(symbol="000001", limit=10)
    assert got.rows == []


# ---------------------------------------------------------------- 유니버스 고르기


def test_universe_takes_the_biggest_by_market_cap():
    _add("000001", "큰회사", close=100_000, shares=1_000_000)
    _add("000002", "작은회사", close=1_000, shares=1_000)
    assert universe.top_symbols(1) == ["000001"]


def test_universe_is_empty_without_quotes():
    assert universe.top_symbols(10) == []
