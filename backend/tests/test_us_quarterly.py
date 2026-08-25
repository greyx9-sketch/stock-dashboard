"""미국 분기 재무 회귀 테스트.

국내와 같은 함정(3개월치와 누적을 섞는 것)에 더해 **미국에만 있는 함정 둘**을 못 박는다.
둘 다 실제로 걸렸고, 화면에는 그럴듯한 숫자가 나오고 있었다(2026-08-25).

1. **같은 `(회계연도, 분기)` 태그에 두 기간이 온다.** 10-Q 가 전년 동기를 나란히 싣는데
   그 비교분에도 보고서의 회계연도가 붙는다. '나중에 제출된 것'을 고르면 비교분이
   이겨서 **분기가 한 해씩 밀린다.** 기간이 늦은 쪽이 당기다.

2. **재무상태표도 같은 이유로 틀렸다.** 10-Q 대차대조표에는 당분기말과 직전 연도말이
   함께 실린다. 잘못 고르면 한 회계연도의 세 분기가 **전부 같은 자산총계**를 갖는다.
"""

from __future__ import annotations

from decimal import Decimal

from app.routers.us_stocks import _to_us_quarter, _us_q4
from app.services.sec_quarterly import extract_quarters

CIK = "0000320193"


def _fact(start, end, val, *, fy, fp, filed="2026-01-01", accn="a"):
    return {"start": start, "end": end, "val": val, "form": "10-Q",
            "fy": fy, "fp": fp, "filed": filed, "accn": accn}


def _instant(end, val, *, fy, fp, filed="2026-01-01"):
    return {"end": end, "val": val, "form": "10-Q", "fy": fy, "fp": fp,
            "filed": filed, "accn": "a"}


def _facts(revenue=(), net_income=(), assets=()):
    return {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": list(revenue)}
                },
                "NetIncomeLoss": {"units": {"USD": list(net_income)}},
                "Assets": {"units": {"USD": list(assets)}},
            }
        }
    }


def _by_period(rows):
    return {(r.fiscal_year, r.quarter): r for r in rows}


# ---------------------------------------------------------------- 함정 1


def test_comparative_from_a_later_filing_does_not_win():
    """**회귀 방지.** 전년 비교분이 같은 태그를 달고 **더 나중에** 제출된다.

    제출 시점으로 고르면 비교분이 이겨 분기가 한 해씩 밀린다.
    """
    rows = extract_quarters(
        _facts(
            revenue=[
                # FY2026 1분기 — 원래 보고서
                _fact("2025-09-28", "2025-12-27", 143_800, fy=2026, fp="Q1", filed="2026-01-30"),
                # FY2025 1분기가 비교분으로 다시 실렸다. 태그는 fy=2026 이고 제출은 더 나중이다.
                _fact("2024-09-29", "2024-12-28", 124_300, fy=2026, fp="Q1", filed="2026-01-30",
                      accn="b"),
            ]
        )
    )
    got = _by_period(rows)[(2026, 1)]
    assert got.values["revenue"] == 143_800, "비교분을 당기로 집었다"
    assert got.period_end == "2025-12-27"


def test_balance_sheet_takes_the_quarter_end_not_the_prior_year_end():
    """**회귀 방지.** 10-Q 대차대조표에는 분기말과 직전 연도말이 함께 실린다.

    잘못 고르면 한 회계연도의 세 분기가 전부 같은 자산총계를 갖는다.
    """
    rows = extract_quarters(
        _facts(
            net_income=[_fact("2025-09-28", "2025-12-27", 42_100, fy=2026, fp="Q1")],
            assets=[
                _instant("2025-12-27", 359_200, fy=2026, fp="Q1"),  # 분기말
                _instant("2025-09-27", 331_500, fy=2026, fp="Q1"),  # 직전 연도말
            ],
        )
    )
    assert _by_period(rows)[(2026, 1)].values["total_assets"] == 359_200


# ---------------------------------------------------------------- 3개월치 vs 누적


def test_three_month_and_cumulative_are_kept_apart():
    """국내와 같은 함정이다. 뒤바뀌면 매출이 두 배로 보이는데 화면은 멀쩡해 보인다."""
    rows = extract_quarters(
        _facts(
            revenue=[
                _fact("2025-12-28", "2026-03-28", 111_200, fy=2026, fp="Q2"),   # 90일
                _fact("2025-09-28", "2026-03-28", 254_900, fy=2026, fp="Q2"),   # 181일
            ]
        )
    )
    got = _by_period(rows)[(2026, 2)]
    assert got.values["revenue"] == 111_200
    assert got.values["revenue_cum"] == 254_900


def test_first_quarter_cumulative_equals_the_quarter():
    """1분기는 누적과 3개월이 같은 기간이다."""
    rows = extract_quarters(
        _facts(revenue=[_fact("2025-09-28", "2025-12-27", 143_800, fy=2026, fp="Q1")])
    )
    got = _by_period(rows)[(2026, 1)]
    assert got.values["revenue"] == got.values["revenue_cum"] == 143_800


def test_annual_facts_are_not_treated_as_quarters():
    """10-K 사실이 섞여 들어오면 분기가 연간값으로 부풀려진다."""
    facts = _facts(revenue=[_fact("2025-09-28", "2026-09-26", 400_000, fy=2026, fp="FY")])
    facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"][
        "units"
    ]["USD"][0]["form"] = "10-K"
    assert extract_quarters(facts) == []


def test_fourth_quarter_is_never_stored():
    """미국도 4분기 10-Q 가 없다. fp=Q4 로 오는 것이 있어도 담지 않는다."""
    rows = extract_quarters(
        _facts(revenue=[_fact("2026-03-29", "2026-06-27", 1, fy=2026, fp="Q4")])
    )
    assert rows == []


def test_nothing_from_empty_facts():
    assert extract_quarters({}) == []
    assert extract_quarters(_facts()) == []


# ---------------------------------------------------------------- 4분기 계산


class _Annual:
    def __init__(self, **kw):
        self.fiscal_year = kw.get("fiscal_year", 2025)
        self.period_end = kw.get("period_end", "2025-09-27")
        self.revenue = kw.get("revenue", 416_200)
        self.gross_profit = kw.get("gross_profit", None)
        self.operating_income = kw.get("operating_income", None)
        self.net_income = kw.get("net_income", None)
        self.total_assets = kw.get("total_assets", 331_500)
        self.total_liabilities = kw.get("total_liabilities", None)
        self.total_equity = kw.get("total_equity", None)


def _q3(**kw):
    base = {
        "fiscal_year": 2025, "quarter": 3, "period_end": "2025-06-28", "derived": False,
        "revenue": 94_000, "gross_profit": None, "operating_income": None, "net_income": None,
        "revenue_cum": 313_700, "gross_profit_cum": None,
        "operating_income_cum": None, "net_income_cum": None,
        "total_assets": None, "total_liabilities": None, "total_equity": None,
    }
    base.update(kw)
    return base


def test_q4_is_annual_minus_nine_months():
    """애플 FY2025 실제 수치 — 416.2 − 313.7 = 102.5십억."""
    q4 = _us_q4(_Annual(), _q3())
    assert q4["revenue"] == 416_200 - 313_700
    assert q4["derived"] is True
    assert q4["revenue_cum"] == 416_200  # 누적은 연간 그 자체다


def test_q4_balance_sheet_is_the_annual_value_not_a_subtraction():
    assert _us_q4(_Annual(), _q3())["total_assets"] == 331_500


def test_q4_needs_the_third_quarter():
    """연간값을 4분기인 척 내보내면 네 배 부풀려진다. 비어 있는 편이 낫다."""
    assert _us_q4(_Annual(), None) is None


def test_q4_is_skipped_when_nothing_can_be_computed():
    assert _us_q4(_Annual(revenue=None), _q3(revenue_cum=None)) is None


# ---------------------------------------------------------------- 증가율·표시


def test_growth_compares_with_the_same_quarter_last_year():
    """전분기가 아니라 전년 동분기와 견준다. 분기 실적은 계절을 심하게 탄다."""
    now = _q3(fiscal_year=2026, revenue=109_400)
    ago = _q3(fiscal_year=2025, revenue=94_000)
    assert _to_us_quarter(now, ago).revenue_yoy == Decimal("16.38")


def test_label_carries_the_fiscal_year():
    """회계연도가 회사마다 달라 FY 를 붙여야 헷갈리지 않는다."""
    assert _to_us_quarter(_q3(fiscal_year=2026), None).label == "FY2026 3Q"


def test_period_end_survives_to_the_response():
    """**FY2026 1Q 가 언제인지는 종료일로만 알 수 있다.**"""
    assert _to_us_quarter(_q3(period_end="2026-06-27"), None).period_end == "2026-06-27"
