"""밸류에이션 — PER · PBR · 배당수익률.

기획서 5.2. **모든 값을 원자료에서 직접 계산한다**(CLAUDE.md 절대 규칙 3). 저장하지도
않는다 — 주가가 1초마다 바뀌므로 저장하는 순간 낡은 값이 된다.

## 무엇을 분모로 쓰는가 — 이 파일에서 가장 중요한 결정

**지배주주 몫을 쓴다.** 연결 재무제표의 당기순이익·자본총계에는 비지배지분(자회사의
남의 몫)이 섞여 있어서, 그대로 나누면 주주가 가진 값어치와 다른 숫자가 나온다.
실제로 차이가 크다(2025년 실적):

| 회사 | 당기순이익 → 지배주주 | 자본총계 → 지배주주 |
| --- | --- | --- |
| LG화학 | -0.98조 → **-1.82조** | 47.1조 → **32.9조** |
| 카카오 | 0.52조 → 0.49조 | 15.2조 → **11.3조** |

별도재무제표(OFS)에는 비지배지분이라는 개념 자체가 없다. 그때는 지배주주 몫 줄이
아예 없고, 전체가 곧 지배주주 몫이므로 그대로 쓴다 — 물러선 것이 아니라 정의상 같다.

## 상장주식수는 보통주만이다

KRX 가 종목별로 주는 값이라 우선주는 다른 종목코드로 따로 잡힌다(삼성전자 58.5억주 /
삼성전자우 8.0억주). 그래서 여기서 내는 EPS·BPS 는 **보통주 기준**이고, 우선주 몫이
빠진 값이다. 국내 데이터 제공사들이 쓰는 관례와 같지만, 화면에 그 사실을 밝힌다.

우선주 종목 자체(005935 등)는 DART 고유번호 매핑이 없어 이 경로까지 오지 못한다.

## 자기주식은 빼지 않았다

KRX 상장주식수에는 회사가 들고 있는 자기주식이 포함된다. 엄밀히는 빼야 EPS 가 정확한데,
자기주식 수량은 사업보고서 본문을 파싱해야 나온다. 그 절반짜리를 붙이느니 밝히고 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.models.base import get_session
from app.models.financial import DartFinancial
from app.models.quote import KrxDailyQuote
from app.services import dividends as dividends_service
from app.services.price_poller import poller

# 소수 둘째 자리까지. 배수(PER·PBR)와 백분율(배당수익률) 모두 그 정도면 충분하다.
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Valuation:
    """한 종목의 밸류에이션. 값마다 **어느 시점 무엇으로 냈는지**를 함께 든다."""

    price: int
    price_label: str  # "실시간" / "확정 종가 (2026-08-18)"
    listed_shares: int
    market_cap: int

    fiscal_year: int | None
    fs_label: str | None  # 연결 / 별도
    owners_basis: bool  # 지배주주 몫으로 계산했는가

    eps: int | None
    bps: int | None
    dps: int | None
    dps_year: int | None

    per: Decimal | None
    pbr: Decimal | None
    dividend_yield: Decimal | None

    # 계산하지 못한 값의 사정. 화면에 "—" 대신 이 문장을 보여준다.
    per_note: str | None = None
    pbr_note: str | None = None
    dividend_note: str | None = None


def _latest_quote(symbol: str) -> KrxDailyQuote | None:
    with get_session() as session:
        return (
            session.execute(
                select(KrxDailyQuote)
                .where(KrxDailyQuote.symbol == symbol)
                .order_by(KrxDailyQuote.trade_date.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )


def _latest_financial(corp_code: str, fs_div: str) -> DartFinancial | None:
    with get_session() as session:
        return (
            session.execute(
                select(DartFinancial)
                .where(DartFinancial.corp_code == corp_code)
                .where(DartFinancial.fs_div == fs_div)
                .order_by(DartFinancial.fiscal_year.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )


def _live_price(symbol: str) -> int | None:
    """폴러·웹소켓이 들고 있는 현재가. 아직 못 받았으면 None."""
    cached = poller.snapshot([symbol]).get(symbol)
    return int(cached.last_price) if cached else None


def _ratio(numerator: int, denominator: int | None) -> Decimal | None:
    if not denominator:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(CENT)


def compute(symbol: str, corp_code: str, fs_div: str, fs_label: str) -> Valuation | None:
    """한 종목의 밸류에이션. 주가나 상장주식수가 없으면 아무것도 못 내므로 None."""
    quote = _latest_quote(symbol)
    if quote is None or not quote.listed_shares:
        return None

    # 현재가를 쓰되, 아직 못 받았으면 KRX 확정 종가로 물러선다. 어느 쪽인지 밝힌다 —
    # 둘은 기준일이 다르고, 확정 종가는 하루 늦다.
    live = _live_price(symbol)
    price = live if live else quote.close
    price_label = "실시간" if live else f"확정 종가 ({quote.trade_date})"

    shares = quote.listed_shares
    market_cap = price * shares

    financial = _latest_financial(corp_code, fs_div)
    dividend = dividends_service.latest(corp_code)

    eps = bps = None
    per = pbr = None
    per_note = pbr_note = None
    fiscal_year = None
    owners_basis = False

    if financial is None:
        per_note = pbr_note = "재무 자료를 아직 받지 못했습니다."
    else:
        fiscal_year = financial.fiscal_year
        # 별도재무제표에는 비지배지분이 없다 — 전체가 곧 지배주주 몫이다.
        income = financial.net_income_owners
        equity = financial.total_equity_owners
        owners_basis = income is not None or equity is not None
        if income is None:
            income = financial.net_income
        if equity is None:
            equity = financial.total_equity

        if income is None:
            per_note = "순이익 계정이 없는 회사입니다."
        elif income <= 0:
            # 적자면 PER 이 뜻을 잃는다. 음수 배수를 보여주면 "싸다"로 잘못 읽힌다.
            per_note = "적자라 PER 을 내지 않습니다."
        else:
            eps = income // shares
            per = _ratio(market_cap, income)

        if equity is None:
            pbr_note = "자본 계정이 없는 회사입니다."
        elif equity <= 0:
            pbr_note = "자본잠식이라 PBR 을 내지 않습니다."
        else:
            bps = equity // shares
            pbr = _ratio(market_cap, equity)

    dps = dps_year = None
    dividend_yield = None
    dividend_note = None
    if dividend is None:
        dividend_note = "배당 자료를 아직 받지 못했습니다."
    elif dividend.dps_common is None:
        dividend_note = f"{dividend.fiscal_year}년에 주당 현금배당이 없었습니다."
    else:
        dps = dividend.dps_common
        dps_year = dividend.fiscal_year
        # **DART 가 알려주는 현금배당수익률을 쓰지 않는다.** 그건 그 해 결산일 기준이라
        # 지금 주가와 다르다. 지금 사면 얼마를 받는지가 궁금한 값이므로 현재가로 낸다.
        dividend_yield = (Decimal(dps) / Decimal(price) * 100).quantize(CENT)

    return Valuation(
        price=price,
        price_label=price_label,
        listed_shares=shares,
        market_cap=market_cap,
        fiscal_year=fiscal_year,
        fs_label=fs_label if financial is not None else None,
        owners_basis=owners_basis,
        eps=eps,
        bps=bps,
        dps=dps,
        dps_year=dps_year,
        per=per,
        pbr=pbr,
        dividend_yield=dividend_yield,
        per_note=per_note,
        pbr_note=pbr_note,
        dividend_note=dividend_note,
    )
