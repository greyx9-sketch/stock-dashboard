"""분기 재무 회귀 테스트.

여기서 지켜야 할 것은 **기간을 섞지 않는 것**이다. 분기 보고서의 손익 줄은 3개월치와
누적을 나란히 들고 오는데, 둘을 바꿔 읽으면 숫자가 그럴듯해서 알아채기 어렵다 —
2분기 매출 74조 자리에 상반기 154조가 들어가도 화면은 멀쩡해 보인다.

그래서 이 파일의 중심은 **검산**이다. 1~4분기 3개월치의 합이 공시된 연간과 맞아야 한다.
실제 삼성전자 2025 년 수치로 확인했고(합 333.61조 = 연간 333.61조), 같은 성질을
여기서 못 박는다.

4분기는 DART 에 보고서가 없어 `연간 − 3분기 누적`으로 만든다. 이것이 이 기능에서
유일한 계산값이라 따로 확인한다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.financial import DartFinancial
from app.routers.financials import _minus, _q4_from_annual, _to_quarter
from app.services.dart_quarterly import due_quarters, extract_quarter

# ---------------------------------------------------------------- 원문을 흉내 낸 응답
#
# 실제 응답에서 이 기능이 쓰는 필드만 남겼다(2026-08-24 삼성전자 반기 확인).


def _is_row(account_id: str, name: str, *, qtr: str, cum: str) -> dict[str, str]:
    """손익계산서 한 줄. 3개월치와 누적을 함께 들고 온다."""
    return {
        "rcept_no": "20250814003156",
        "sj_div": "IS",
        "account_id": account_id,
        "account_nm": name,
        "thstrm_amount": qtr,
        "thstrm_add_amount": cum,
        "currency": "KRW",
    }


def _bs_row(account_id: str, name: str, *, amount: str) -> dict[str, str]:
    """재무상태표 한 줄. **누적 칸이 없다** — 잔액에는 '3개월치'가 없기 때문이다."""
    return {
        "rcept_no": "20250814003156",
        "sj_div": "BS",
        "account_id": account_id,
        "account_nm": name,
        "thstrm_amount": amount,
        "frmtrm_amount": "514531948000000",  # 전기말. 전년 동분기가 아니다.
        "currency": "KRW",
    }


def _half_response() -> list[dict[str, str]]:
    """삼성전자 2025 반기보고서의 실제 수치를 옮겼다."""
    return [
        _is_row("ifrs-full_Revenue", "매출액", qtr="74566317000000", cum="153706820000000"),
        _is_row("ifrs-full_GrossProfit", "매출총이익", qtr="27000000000000", cum="55000000000000"),
        _is_row("dart_OperatingIncomeLoss", "영업이익", qtr="4676000000000", cum="11360000000000"),
        _is_row("ifrs-full_ProfitLoss", "당기순이익", qtr="5120000000000", cum="13340000000000"),
        _bs_row("ifrs-full_Assets", "자산총계", amount="504875185000000"),
        _bs_row("ifrs-full_Liabilities", "부채총계", amount="120000000000000"),
        _bs_row("ifrs-full_Equity", "자본총계", amount="384875185000000"),
    ]


# ---------------------------------------------------------------- 기간을 섞지 않는가


def test_quarter_amount_is_three_months_not_cumulative():
    """**이 파일에서 가장 중요한 테스트.**

    반기보고서의 `thstrm_amount` 는 2분기 3개월치(74.57조)이지 상반기 누적(153.71조)이
    아니다. 뒤바뀌면 매출이 두 배로 보이는데 화면은 멀쩡해 보인다.
    """
    q = extract_quarter(_half_response(), year=2025, quarter=2)
    assert q is not None
    assert q.values["revenue"] == 74_566_317_000_000
    assert q.values["revenue_cum"] == 153_706_820_000_000


def test_balance_sheet_has_no_cumulative():
    """자산·부채·자본은 잔액이라 누적 칸을 만들지 않는다."""
    q = extract_quarter(_half_response(), year=2025, quarter=2)
    assert q.values["total_assets"] == 504_875_185_000_000
    assert "total_assets_cum" not in q.values


def test_first_quarter_cumulative_falls_back_to_itself():
    """1분기는 누적과 당분기가 같은 기간이다. 누적 칸을 비워 보내는 회사가 있어도 채운다.

    계산이 아니라 정의상 같은 값이라 채워도 원값 원칙에 어긋나지 않는다.
    """
    rows = [_is_row("ifrs-full_Revenue", "매출액", qtr="79140503000000", cum="")]
    q = extract_quarter(rows, year=2025, quarter=1)
    assert q.values["revenue"] == 79_140_503_000_000
    assert q.values["revenue_cum"] == 79_140_503_000_000


def test_missing_cumulative_is_not_invented_for_later_quarters():
    """2분기 이후에는 누적을 지어내지 않는다. 없으면 없는 채로 둔다."""
    rows = [_is_row("ifrs-full_Revenue", "매출액", qtr="74566317000000", cum="")]
    q = extract_quarter(rows, year=2025, quarter=2)
    assert q.values["revenue"] == 74_566_317_000_000
    assert q.values["revenue_cum"] is None


def test_missing_account_is_none_not_zero():
    """금융지주에는 매출액 계정이 아예 없다. 0 으로 채우면 영업이익률이 터진다."""
    rows = [_is_row("dart_OperatingIncomeLoss", "영업이익", qtr="2130000000000", cum="4430000000000")]
    q = extract_quarter(rows, year=2025, quarter=2)
    assert q.values["revenue"] is None
    assert q.values["operating_income"] == 2_130_000_000_000


def test_empty_response_gives_nothing():
    assert extract_quarter([], year=2025, quarter=2) is None


def test_all_blank_gives_nothing():
    """계정은 있는데 금액이 전부 비면 행을 만들지 않는다. 빈 막대가 그려진다."""
    rows = [_is_row("ifrs-full_Revenue", "매출액", qtr="", cum="")]
    assert extract_quarter(rows, year=2025, quarter=2) is None


# ---------------------------------------------------------------- 4분기 (유일한 계산값)


def _annual(**kwargs) -> DartFinancial:
    base = dict(
        corp_code="00126380",
        fiscal_year=2025,
        fs_div="CFS",
        revenue=333_605_938_000_000,
        gross_profit=None,
        operating_income=23_530_000_000_000 + 20_070_000_000_000,
        net_income=None,
        total_assets=566_942_110_000_000,
        total_liabilities=None,
        total_equity=None,
        currency="KRW",
        receipt_no="20260310002820",
    )
    base.update(kwargs)
    return DartFinancial(**base)


def _q3(**kwargs) -> dict:
    base = {
        "fiscal_year": 2025,
        "quarter": 3,
        "derived": False,
        "revenue": 86_061_747_000_000,
        "gross_profit": None,
        "operating_income": None,
        "net_income": None,
        "revenue_cum": 239_768_567_000_000,
        "gross_profit_cum": None,
        "operating_income_cum": 23_530_000_000_000,
        "net_income_cum": None,
        "total_assets": None,
        "total_liabilities": None,
        "total_equity": None,
        "currency": "KRW",
        "receipt_no": "20251114002447",
    }
    base.update(kwargs)
    return base


def test_q4_is_annual_minus_nine_months():
    """4분기 3개월치 = 연간 − 3분기 누적. 삼성전자 2025 년 실제 수치로 확인한 값이다."""
    q4 = _q4_from_annual(_annual(), _q3())
    assert q4["revenue"] == 333_605_938_000_000 - 239_768_567_000_000
    assert q4["derived"] is True


def test_q4_cumulative_is_the_annual_figure_itself():
    """4분기까지의 누적이 곧 한 해 전체다. 이건 계산이 아니라 원값이다."""
    q4 = _q4_from_annual(_annual(), _q3())
    assert q4["revenue_cum"] == 333_605_938_000_000


def test_q4_balance_sheet_comes_from_the_annual_report():
    """기말 잔액은 사업보고서에 그대로 적혀 있다. 빼기를 하지 않는다."""
    q4 = _q4_from_annual(_annual(), _q3())
    assert q4["total_assets"] == 566_942_110_000_000


def test_q4_needs_the_third_quarter():
    """**3분기가 없으면 4분기를 만들지 않는다.**

    여기서 연간값을 그대로 4분기라고 내보내면 네 배 부풀려진 막대가 그려진다.
    비어 있는 편이 낫다.
    """
    assert _q4_from_annual(_annual(), None) is None


def test_q4_is_skipped_when_nothing_can_be_computed():
    """뺄 것이 하나도 없으면 빈 행을 만들지 않는다."""
    annual = _annual(revenue=None, operating_income=None)
    q3 = _q3(revenue_cum=None, operating_income_cum=None)
    assert _q4_from_annual(annual, q3) is None


def test_q4_can_be_negative():
    """4분기에 적자를 낸 회사가 실제로 있다. 음수를 감추지 않는다."""
    annual = _annual(revenue=100)
    q3 = _q3(revenue_cum=150)
    assert _q4_from_annual(annual, q3)["revenue"] == -50


def test_minus_needs_both_sides():
    assert _minus(None, 10) is None
    assert _minus(10, None) is None
    assert _minus(10, 3) == 7


def test_four_quarters_sum_to_the_annual_figure():
    """**검산.** 1~4분기 3개월치의 합이 공시된 연간과 같아야 한다.

    삼성전자 2025: 79.14 + 74.57 + 86.06 + (계산된 4분기) = 333.61조.
    이 성질이 깨지면 어딘가에서 누적과 3개월치를 섞은 것이다.
    """
    q1, q2, q3_amount = 79_140_503_000_000, 74_566_317_000_000, 86_061_747_000_000
    annual_total = 333_605_938_000_000

    q4 = _q4_from_annual(_annual(), _q3(revenue_cum=q1 + q2 + q3_amount))
    assert q1 + q2 + q3_amount + q4["revenue"] == annual_total


# ---------------------------------------------------------------- 증가율은 전년 동분기와


def test_growth_compares_with_the_same_quarter_last_year():
    """전분기가 아니라 **전년 동분기**와 견준다.

    분기 실적은 계절을 심하게 탄다. 직전 분기와 비교하면 해마다 같은 자리에서 같은
    착시가 생긴다.
    """
    now = _q3(fiscal_year=2025, quarter=3, revenue=86_061_747_000_000)
    year_ago = _q3(fiscal_year=2024, quarter=3, revenue=79_098_731_000_000)
    point = _to_quarter(now, year_ago)
    # 소수 둘째 자리로 고정된 Decimal 이다. float 과 견주면 타입이 안 맞는다.
    assert point.revenue_yoy == Decimal("8.80")


def test_growth_is_blank_without_a_comparison():
    """비교할 전년이 없으면 비운다. 화면에서 '-' 로 보이는 편이 틀린 숫자보다 낫다."""
    assert _to_quarter(_q3(), None).revenue_yoy is None


def test_label_is_readable():
    assert _to_quarter(_q3(fiscal_year=2025, quarter=3), None).label == "2025 3Q"


# ---------------------------------------------------------------- 언제 무엇을 부를 것인가


def test_unfiled_quarters_are_not_requested():
    """8월에는 3분기 보고서가 아직 없다. 부르면 빈 응답이라 호출만 버린다."""
    got = due_quarters(date(2026, 8, 24), years=1)
    assert (2026, 3) not in got
    assert (2026, 2) in got
    assert (2026, 1) in got


def test_newest_quarter_comes_first():
    """최근 것부터 채운다 — 사람이 먼저 보는 것이 최근 분기다."""
    got = due_quarters(date(2026, 8, 24), years=2)
    assert got[0] == (2026, 2)
    assert got == sorted(got, reverse=True)


def test_january_falls_back_to_last_year():
    """연초에는 올해 것이 하나도 없다. 작년 분기들로 채워야 화면이 비지 않는다."""
    got = due_quarters(date(2026, 1, 10), years=2)
    assert (2026, 1) not in got
    assert (2025, 3) in got


def test_years_limits_how_far_back_we_go():
    got = due_quarters(date(2026, 8, 24), years=3)
    assert min(year for year, _ in got) == 2024
