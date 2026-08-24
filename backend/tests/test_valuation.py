"""밸류에이션 회귀 테스트.

이 기능에서 틀리기 쉬운 것은 나눗셈이 아니라 **분모를 무엇으로 잡느냐**다. 숫자는 늘
그럴듯하게 나오고, 30% 어긋나도 화면만 봐서는 알 수 없다.

실제로 한 번 틀렸다(2026-08-25). 지배주주 몫 칸을 새로 뽑기 시작했는데, 이미 저장돼
있던 종목은 그 칸이 빈 채로 남아 옛 값으로 계산됐다 — 카카오 PBR 이 1.04 로 나왔고
바로잡으니 1.41 이었다. 그 회귀를 아래에서 못 박는다.

다음 넷을 지킨다:

1. 분모는 **지배주주 몫**이다. 연결 순이익·자본에는 비지배지분이 섞여 있다.
2. 별도재무제표에는 지배주주 구분이 없다. 그때 전체를 쓰는 것은 물러선 것이 아니라
   정의상 같은 값이다.
3. **적자와 자료 없음을 구분한다.** 둘 다 "—" 로 뭉개면 사람이 판단할 수 없다.
4. 음수 PER 을 만들지 않는다. 배수가 음수면 "싸다"로 잘못 읽힌다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.base import get_session, init_db
from app.models.dividend import DartDividend
from app.models.financial import DartFinancial
from app.models.quote import KrxDailyQuote
from app.services import valuation
from app.services.dividends import extract as extract_dividend

CORP = "00126380"
SYMBOL = "005930"
SHARES = 1_000_000  # 백만 주. 나눗셈이 눈으로 검산되는 값으로 잡는다.


@pytest.fixture(autouse=True)
def _clean_db():
    init_db()
    with get_session() as session:
        session.query(KrxDailyQuote).delete()
        session.query(DartFinancial).delete()
        session.query(DartDividend).delete()
        session.commit()


def _quote(close: int = 100_000, shares: int = SHARES) -> None:
    with get_session() as session:
        session.add(
            KrxDailyQuote(
                trade_date="2026-08-21",
                symbol=SYMBOL,
                isin="KR7005930003",
                name="삼성전자",
                market="KOSPI",
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
        session.commit()


def _financial(**kwargs) -> None:
    base = dict(
        corp_code=CORP,
        fiscal_year=2025,
        fs_div="CFS",
        net_income=20_000_000_000,  # 200억 — 전체
        net_income_owners=10_000_000_000,  # 100억 — 지배주주 몫 (절반)
        total_equity=40_000_000_000,
        total_equity_owners=20_000_000_000,
        currency="KRW",
        receipt_no="20260310002820",
        extract_version=2,
    )
    base.update(kwargs)
    with get_session() as session:
        session.add(DartFinancial(**base))
        session.commit()


def _dividend(**kwargs) -> None:
    base = dict(corp_code=CORP, fiscal_year=2025, dps_common=2_000, receipt_no="20260310002820")
    base.update(kwargs)
    with get_session() as session:
        session.add(DartDividend(**base))
        session.commit()


def _compute():
    return valuation.compute(SYMBOL, CORP, "CFS", "연결")


# ---------------------------------------------------------------- 분모


def test_per_uses_the_owners_share_not_the_whole():
    """**이 파일에서 가장 중요한 테스트.**

    시총 1,000억 / 지배주주순이익 100억 = 10배.
    전체 순이익(200억)을 쓰면 5배가 나온다 — 절반으로 싸 보인다.
    """
    _quote(close=100_000)  # 시총 = 10만원 × 100만주 = 1,000억
    _financial()
    result = _compute()
    assert result.per == Decimal("10.00")
    assert result.eps == 10_000  # 100억 / 100만주
    assert result.owners_basis is True


def test_pbr_uses_the_owners_share_not_the_whole():
    """카카오가 이것 때문에 1.04 로 나왔었다. 실제 값은 1.41 이었다."""
    _quote(close=100_000)
    _financial()
    result = _compute()
    assert result.pbr == Decimal("5.00")  # 1,000억 / 200억
    assert result.bps == 20_000


def test_separate_statements_fall_back_to_the_whole():
    """별도재무제표에는 비지배지분이 없다. 전체를 쓰는 것이 곧 지배주주 몫이다."""
    _quote(close=100_000)
    _financial(net_income_owners=None, total_equity_owners=None)
    result = _compute()
    # 전체 순이익 200억이 곧 지배주주 몫이다 → 시총 1,000억 / 200억 = 5배.
    assert result.per == Decimal("5.00")
    assert result.eps == 20_000
    assert result.owners_basis is False


# ---------------------------------------------------------------- 못 내는 경우


def test_loss_making_company_gets_no_per():
    """적자면 PER 이 뜻을 잃는다. 음수 배수를 보여주면 '싸다'로 잘못 읽힌다."""
    _quote()
    _financial(net_income_owners=-5_000_000_000)
    result = _compute()
    assert result.per is None
    assert "적자" in result.per_note


def test_negative_equity_gets_no_pbr():
    """자본잠식도 같다."""
    _quote()
    _financial(total_equity_owners=-1)
    result = _compute()
    assert result.pbr is None
    assert "자본잠식" in result.pbr_note


def test_missing_financials_say_so_instead_of_pretending():
    """**적자와 '자료 없음'은 다르다.** 둘 다 '—' 면 사람이 판단할 수 없다."""
    _quote()
    result = _compute()
    assert result.per is None and result.pbr is None
    assert "받지 못했" in result.per_note
    assert "적자" not in result.per_note


def test_no_dividend_is_not_zero_percent():
    """배당을 안 한 것과 0% 는 다르게 읽힌다."""
    _quote()
    _financial()
    _dividend(dps_common=None)
    result = _compute()
    assert result.dividend_yield is None
    assert "배당이 없었" in result.dividend_note


def test_without_a_quote_nothing_can_be_computed():
    """주가나 상장주식수가 없으면 아무 지표도 못 낸다."""
    _financial()
    assert _compute() is None


# ---------------------------------------------------------------- 배당수익률


def test_dividend_yield_uses_the_current_price():
    """DART 가 주는 수익률은 그 해 결산일 기준이다. 지금 사면 얼마인지가 궁금한 값이다."""
    _quote(close=100_000)
    _financial()
    _dividend(dps_common=2_000, reported_yield=9.99)
    result = _compute()
    assert result.dividend_yield == Decimal("2.00")  # 2,000 / 100,000
    assert result.dps == 2_000


# ---------------------------------------------------------------- 주가 출처


def test_price_label_says_which_price_was_used():
    """실시간과 확정 종가는 기준일이 다르다. 어느 쪽인지 밝히지 않으면 비교가 틀린다."""
    _quote(close=100_000)
    _financial()
    result = _compute()
    assert "확정 종가" in result.price_label
    assert "2026-08-21" in result.price_label


def test_market_cap_is_price_times_shares():
    _quote(close=100_000, shares=SHARES)
    _financial()
    result = _compute()
    assert result.market_cap == 100_000 * SHARES


# ---------------------------------------------------------------- 배당 응답 읽기


def _div_row(se: str, kind: str, value: str) -> dict[str, str]:
    return {
        "rcept_no": "20260310002820",
        "se": se,
        "stock_knd": kind,
        "thstrm": value,
        "stlm_dt": "2025-12-31",
    }


def test_dividend_extract_separates_common_and_preferred():
    """보통주와 우선주는 배당금이 다르다(삼성전자 2025: 1,668 / 1,669)."""
    rows = [
        _div_row("주당 현금배당금(원)", "보통주", "1,668"),
        _div_row("주당 현금배당금(원)", "우선주", "1,669"),
        _div_row("현금배당금총액(백만원)", "-", "11,107,906"),
    ]
    got = extract_dividend(rows, 2025)
    assert got.dps_common == 1_668
    assert got.dps_preferred == 1_669
    assert got.total_cash == 11_107_906 * 1_000_000  # 백만원 → 원


def test_dividend_extract_tolerates_spacing():
    """회사마다 띄어쓰기가 다르다. 공백을 걷어내고 맞춘다."""
    rows = [_div_row("주당현금배당금(원)", "보통주", "500")]
    assert extract_dividend(rows, 2025).dps_common == 500


def test_dividend_dash_means_no_dividend_not_zero():
    """'-' 를 0 으로 바꾸면 '배당 0원을 줬다'가 된다. 안 준 것과 다르다."""
    rows = [
        _div_row("주당 현금배당금(원)", "보통주", "-"),
        _div_row("현금배당금총액(백만원)", "-", "1,000"),
    ]
    got = extract_dividend(rows, 2025)
    assert got.dps_common is None
    assert got.total_cash == 1_000_000_000


def test_dividend_extract_gives_nothing_when_empty():
    assert extract_dividend([], 2025) is None
    assert extract_dividend([_div_row("주당 현금배당금(원)", "보통주", "-")], 2025) is None


# ---------------------------------------------------------------- 백필 (회귀)


def test_rows_written_before_the_new_columns_are_refetched():
    """**회귀(2026-08-25).** 지배주주 칸을 추가하기 전에 저장된 행은 그 칸이 비어 있다.

    '이미 가지고 있다'로 치면 영영 채워지지 않고, PER·PBR 이 비지배지분 섞인 값으로
    계산된다. 카카오 PBR 이 1.04(실제 1.41)로 나왔던 것이 이 때문이다.
    """
    from app.services.dart_financials import stored_years

    # 판 번호가 없는 행 = 항목이 늘기 전에 저장된 행.
    _financial(extract_version=None, net_income_owners=None, total_equity_owners=None)
    assert stored_years(CORP, "CFS") == set(), "낡은 행을 '가지고 있다'로 쳤다"


def test_freshly_written_rows_are_not_refetched():
    """반대쪽도 못 박는다 — 채워진 뒤에는 다시 받지 않아야 한다."""
    from app.services.dart_financials import stored_years

    from app.services.dart_financials import EXTRACT_VERSION

    _financial(extract_version=EXTRACT_VERSION)
    assert stored_years(CORP, "CFS") == {2025}


# ---------------------------------------------------------------- 화면 안에서 기준 맞추기


def test_roe_uses_the_same_basis_as_pbr():
    """**한 화면에 기준이 섞이면 안 된다.**

    밸류에이션 블록의 PER·PBR 은 지배주주 몫으로 내는데 바로 아래 재무의 ROE 만 전체로
    내면, 나란히 놓인 두 숫자를 견줄 수 없게 된다.
    """
    from app.routers.financials import _to_year

    row = DartFinancial(
        corp_code=CORP,
        fiscal_year=2025,
        fs_div="CFS",
        net_income=20_000_000_000,
        net_income_owners=10_000_000_000,
        total_equity=40_000_000_000,
        total_equity_owners=20_000_000_000,
        receipt_no="x",
    )
    # 지배주주 기준 = 100억 / 200억 = 50%. 전체 기준이면 200억/400억 = 50% 로 같아지므로
    # 값을 어긋나게 잡아 어느 쪽을 썼는지 드러낸다.
    row.total_equity_owners = 25_000_000_000
    assert _to_year(row, None).roe == Decimal("40.00")  # 100억 / 250억


def test_roe_falls_back_when_owners_share_is_absent():
    """별도재무제표에는 지배주주 구분이 없다. 그때는 전체로 낸다."""
    from app.routers.financials import _to_year

    row = DartFinancial(
        corp_code=CORP,
        fiscal_year=2025,
        fs_div="OFS",
        net_income=20_000_000_000,
        net_income_owners=None,
        total_equity=40_000_000_000,
        total_equity_owners=None,
        receipt_no="x",
    )
    assert _to_year(row, None).roe == Decimal("50.00")


# ================================================================== 미국
#
# 계산은 국내와 같다. 자료의 성질이 달라서 생기는 함정만 못 박는다.


def _sec_fact(*, start: str, end: str, val, form: str = "10-K", filed: str = "2026-01-01") -> dict:
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed, "fp": "FY"}


def test_us_dividend_ignores_quarterly_facts():
    """**회귀 방지.** 회사에 따라 분기 배당을 연간과 **같은 계정**으로 태깅한다.

    MSFT 가 그렇다 — 거르지 않으면 연간 3.64 달러가 분기 0.91 달러로 나온다.
    """
    from app.services.sec_financials import _collect_per_share

    us_gaap = {
        "CommonStockDividendsPerShareDeclared": {
            "units": {
                "USD/shares": [
                    _sec_fact(start="2025-01-01", end="2025-12-31", val=3.64),
                    _sec_fact(start="2025-10-01", end="2025-12-31", val=0.91),
                ]
            }
        }
    }
    got = _collect_per_share(us_gaap)
    assert got[2025]["val"] == 3.64


def test_us_dividend_prefers_declared_over_paid():
    """실제 지급은 분기 시차 때문에 그 해 선언액과 어긋난다. 선언 기준이 맞다."""
    from app.services.sec_financials import _collect_per_share

    us_gaap = {
        "CommonStockDividendsPerShareDeclared": {
            "units": {"USD/shares": [_sec_fact(start="2025-01-01", end="2025-12-31", val=5.80)]}
        },
        "CommonStockDividendsPerShareCashPaid": {
            "units": {"USD/shares": [_sec_fact(start="2025-01-01", end="2025-12-31", val=5.20)]}
        },
    }
    assert _collect_per_share(us_gaap)[2025]["val"] == 5.80


def test_us_shares_come_from_the_dei_namespace():
    """발행주식수는 us-gaap 이 아니라 dei(문서 정보)에 있다. **가장 최근 것**을 쓴다."""
    from app.services.sec_financials import extract_shares

    facts = {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"end": "2025-07-01", "val": 100, "filed": "2025-08-01"},
                            {"end": "2026-07-17", "val": 14_594_180_000, "filed": "2026-08-01"},
                        ]
                    }
                }
            }
        }
    }
    assert extract_shares(facts) == (14_594_180_000, "2026-07-17")


def test_us_shares_missing_is_not_an_error():
    """ETF·DR 처럼 그 항목이 없는 종목이 있다. 터지지 않고 없다고만 답한다."""
    from app.services.sec_financials import extract_shares

    assert extract_shares({}) is None
    assert extract_shares({"facts": {"dei": {}}}) is None


def test_us_refetches_when_shares_are_missing():
    """**회귀 방지(2026-08-25).** 주식수는 나중에 추가한 항목이다.

    그 전에 저장된 회사는 재무만 있고 주식수가 비어 있는데, 연도 수만 보고 건너뛰면
    영영 채워지지 않는다 — 국내에서 지배주주 몫을 추가했을 때와 똑같은 함정이다.
    """
    from app.models.us_company import SecCompany
    from app.services.sec_financials import _has_shares

    with get_session() as session:
        session.add(SecCompany(ticker="AAPL", cik="0000320193", name="Apple Inc."))
        session.commit()
    assert _has_shares("0000320193") is False

    with get_session() as session:
        company = session.get(SecCompany, "AAPL")
        company.shares_outstanding = 14_594_180_000
        session.commit()
    assert _has_shares("0000320193") is True
