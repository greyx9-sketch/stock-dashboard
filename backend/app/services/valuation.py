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
from app.models.corp import DartCorp
from app.models.dividend import DartDividend
from app.models.financial import DartFinancial
from app.models.quote import KrxDailyQuote
from app.services import dividends as dividends_service
from app.services import us_universe
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


# ====================================================================== 여러 종목 한꺼번에
#
# 스크리너는 수백 종목을 한 번에 본다. `compute()` 를 종목마다 부르면 DB 질의가 종목당
# 세 번씩 나가 수백 번이 된다. 아래는 **질의 세 번으로** 전부 읽어 온 뒤 메모리에서 맞춘다.
#
# **주가는 KRX 확정 종가로 통일한다.** 실시간 값은 폴러가 들고 있는 몇십 종목에만 있어서,
# 섞어 쓰면 목록의 어떤 줄은 실시간이고 어떤 줄은 하루 전이 된다. 그런 표에서는 PER 을
# 나란히 비교할 수 없다. 어느 날 종가인지는 화면에 함께 적는다.


@dataclass(frozen=True)
class ScreenRow:
    """스크리너 표의 한 줄. 화면이 그대로 그릴 수 있는 모양이다."""

    symbol: str
    name: str
    market: str
    price: int
    market_cap: int
    trade_date: str

    fiscal_year: int | None
    per: Decimal | None
    pbr: Decimal | None
    roe: Decimal | None
    dividend_yield: Decimal | None
    revenue_growth: Decimal | None


def _percent(numerator: int | None, denominator: int | None) -> Decimal | None:
    if numerator is None or not denominator:
        return None
    return (Decimal(numerator) / Decimal(denominator) * 100).quantize(CENT)


def screen_rows(symbols: list[str] | None = None) -> list[ScreenRow]:
    """유니버스의 지표를 한꺼번에 계산한다. 재무가 없는 종목은 빠진다.

    `symbols` 를 주면 그 종목만 본다(동종업계 비교가 그렇게 쓴다).
    """
    with get_session() as session:
        trade_date = session.execute(
            select(KrxDailyQuote.trade_date).order_by(KrxDailyQuote.trade_date.desc()).limit(1)
        ).scalar()
        if trade_date is None:
            return []

        quote_query = select(KrxDailyQuote).where(KrxDailyQuote.trade_date == trade_date)
        if symbols is not None:
            quote_query = quote_query.where(KrxDailyQuote.symbol.in_(symbols))
        quotes = list(session.execute(quote_query).scalars())

        # 종목코드 → DART 고유번호. 매핑이 없는 종목(우선주 등)은 애초에 재무가 없다.
        corp_query = select(DartCorp.stock_code, DartCorp.corp_code)
        if symbols is not None:
            corp_query = corp_query.where(DartCorp.stock_code.in_(symbols))
        corp_of = dict(session.execute(corp_query).all())

        corp_codes = list(corp_of.values())
        if not corp_codes:
            return []

        # 회사별 **가장 최근** 재무 한 줄씩. 연결(CFS)을 먼저 보고 없으면 별도(OFS).
        financials: dict[tuple[str, str], DartFinancial] = {}
        for row in session.execute(
            select(DartFinancial)
            .where(DartFinancial.corp_code.in_(corp_codes))
            .order_by(DartFinancial.fiscal_year.desc())
        ).scalars():
            financials.setdefault((row.corp_code, row.fs_div), row)

        # 매출 증가율은 전년이 있어야 낸다. 연도별로 통째로 들고 있는다.
        by_year: dict[tuple[str, str, int], DartFinancial] = {}
        for row in session.execute(
            select(DartFinancial).where(DartFinancial.corp_code.in_(corp_codes))
        ).scalars():
            by_year[(row.corp_code, row.fs_div, row.fiscal_year)] = row

        dividend_of: dict[str, DartDividend] = {}
        for row in session.execute(
            select(DartDividend)
            .where(DartDividend.corp_code.in_(corp_codes))
            .order_by(DartDividend.fiscal_year.desc())
        ).scalars():
            dividend_of.setdefault(row.corp_code, row)

    out: list[ScreenRow] = []
    for quote in quotes:
        corp_code = corp_of.get(quote.symbol)
        if corp_code is None or not quote.listed_shares:
            continue

        financial = financials.get((corp_code, "CFS")) or financials.get((corp_code, "OFS"))
        if financial is None:
            continue

        market_cap = quote.close * quote.listed_shares
        income = financial.net_income_owners
        equity = financial.total_equity_owners
        if income is None:
            income = financial.net_income
        if equity is None:
            equity = financial.total_equity

        previous = by_year.get((corp_code, financial.fs_div, financial.fiscal_year - 1))
        dividend = dividend_of.get(corp_code)
        dps = dividend.dps_common if dividend else None

        out.append(
            ScreenRow(
                symbol=quote.symbol,
                name=quote.name,
                market=quote.market,
                price=quote.close,
                market_cap=market_cap,
                trade_date=quote.trade_date,
                fiscal_year=financial.fiscal_year,
                # 적자·자본잠식이면 배수가 뜻을 잃는다. 상세 화면과 같은 규칙이다.
                per=_ratio(market_cap, income) if income and income > 0 else None,
                pbr=_ratio(market_cap, equity) if equity and equity > 0 else None,
                roe=_percent(income, equity) if equity and equity > 0 else None,
                dividend_yield=(
                    (Decimal(dps) / Decimal(quote.close) * 100).quantize(CENT)
                    if dps and quote.close
                    else None
                ),
                revenue_growth=(
                    _percent(financial.revenue - previous.revenue, previous.revenue)
                    if previous is not None
                    and financial.revenue is not None
                    and previous.revenue is not None
                    and previous.revenue > 0
                    else None
                ),
            )
        )
    return out


# ====================================================================== 미국
#
# 국내와 계산은 같고 **자료의 성질이 다르다.** 그 차이만 여기서 다룬다:
#
# 1. **이미 지배주주 기준이다.** us-gaap 은 `NetIncomeLoss`(모회사 몫)와
#    `ProfitLoss`(비지배지분 포함)를 다른 계정으로 두고, 우리 추출기가 앞의 것을 먼저
#    본다(`services/sec_financials.py`). 국내처럼 따로 고를 것이 없다.
#
# 2. **주식수의 기준일이 재무보다 앞선다.** `dei:EntityCommonStockSharesOutstanding`
#    은 가장 최근 제출 서류 표지의 수량이라, 2025 회계연도 재무에 2026년 7월 주식수가
#    붙는 식이다. 시가총액은 그것이 맞지만(지금 주식수 × 지금 주가), 화면에 기준일을
#    함께 적어 사람이 알게 한다.
#
# 3. **확정 종가라는 개념이 없다.** 국내는 KRX 확정 종가라는 물러설 자리가 있지만
#    미국은 토스 현재가뿐이다. 못 받았으면 계산하지 않는다 — 옛 종가로 PER 을 내면
#    그것이 언제 값인지 밝힐 방법이 없다.


@dataclass(frozen=True)
class UsValuation:
    ticker: str
    name: str

    price: Decimal
    shares_outstanding: int
    shares_as_of: str | None
    market_cap: Decimal

    fiscal_year: int | None
    period_end: str | None

    eps: Decimal | None
    bps: Decimal | None
    dps: Decimal | None

    per: Decimal | None
    pbr: Decimal | None
    dividend_yield: Decimal | None

    per_note: str | None = None
    pbr_note: str | None = None
    dividend_note: str | None = None


def _us_price(ticker: str) -> Decimal | None:
    """이 종목의 주가. 폴러가 들고 있는 것을 먼저, 없으면 받아 둔 종가로.

    **폴러가 못 받는 종목이 있다.** 종류주식을 SEC 는 하이픈으로(`BRK-A`), 토스는
    점으로(`BRK.A`) 쓰는데 폴러는 우리 티커를 그대로 물어본다. 그래서 버크셔는
    현재가가 영영 오지 않고, 그러면 밸류에이션 전체가 "낼 수 없습니다"가 되어
    **목록에는 있는데 눌러도 안 열리는 줄**이 된다.

    야간에 받아 둔 종가는 그 표기를 맞춰서 받는다(`us_universe._toss_aliases`).
    실시간만큼 새것은 아니지만, PER·PBR 은 분기 재무를 분모로 쓰는 값이라
    몇 시간 묵은 주가로도 뜻이 상하지 않는다. 화면의 '현재가'는 이 값이 아니라
    실시간 시세를 따로 받아 그린다.

    폴러 자체를 고치는 편이 근본이지만 그쪽은 웹소켓 구독까지 얽혀 있어
    따로 손봐야 한다.
    """
    cached = poller.snapshot([ticker]).get(ticker)
    if cached is not None:
        return cached.last_price

    from app.models.us_company import SecCompany

    with get_session() as session:
        return session.execute(
            select(SecCompany.last_close).where(SecCompany.ticker == ticker)
        ).scalar()


def us_shares(company) -> int | None:
    """시가총액·EPS 를 낼 때 쓸 주식수. **한 회사의 전체 주식수여야 한다.**

    SEC 가 주는 `dei:EntityCommonStockSharesOutstanding` 은 10-K 표지에 적힌
    **종류주식별** 수다. 클래스가 하나뿐인 회사는 그것이 곧 전체지만, 여럿이면
    한 종류의 수만 들어온다. 그대로 시가총액을 내면 통째로 축소된다 —
    마스터카드가 7.2배, 비자가 4.0배, 나이키·컴캐스트가 1.7배 작게 잡혔다.

    **이것이 가장 나쁜 방식으로 드러난다.** 시총이 작으면 PER 도 작고, 스크리너에서
    'PER 낮은 순'으로 세우면 틀린 값들이 맨 위로 올라온다. 실제로 마스터카드가
    PER 4.78 로 두 번째 줄에 있었다. 값이 비는 것과 달리 틀린 값은 사람이 믿는다.

    그래서 토스가 티커별로 주는 상장주식수를 먼저 쓴다. 이쪽은 회사 전체 수다
    (컴캐스트 35.5억주 = A주 + B주). 없으면 SEC 값으로 물러선다 — 유니버스 밖
    종목은 아직 받아 두지 않았고, 클래스가 하나인 회사는 두 값이 같다.
    """
    return company.listed_shares or company.shares_outstanding


def compute_us(ticker: str) -> UsValuation | None:
    """미국 종목의 밸류에이션. 주가나 주식수가 없으면 None."""
    from app.models.us_company import SecCompany, SecFinancial

    with get_session() as session:
        company = session.execute(
            select(SecCompany).where(SecCompany.ticker == ticker)
        ).scalars().first()
        if company is None or not us_shares(company):
            return None
        financial = session.execute(
            select(SecFinancial)
            .where(SecFinancial.cik == company.cik)
            .order_by(SecFinancial.fiscal_year.desc())
            .limit(1)
        ).scalars().first()

    price = _us_price(ticker)
    if price is None:
        return None

    shares = us_shares(company)
    # **주식수의 기준일은 그 수를 준 쪽의 것이어야 한다.** SEC 값을 쓰면 10-K 표지
    # 날짜(`shares_as_of`)가 맞지만, 토스의 상장주식수를 쓰면서 SEC 날짜를 그대로
    # 붙이면 "488,450주 · 2011-04-29 기준"처럼 서로 다른 출처가 한 줄에 섞인다.
    # 화면이 이 날짜를 근거로 내세우는 자리라 조용히 틀리면 알아채기 어렵다.
    shares_as_of = company.shares_as_of
    if company.listed_shares and company.last_close_at:
        shares_as_of = company.last_close_at.date().isoformat()

    # 목록(`us_screen_rows`)과 같은 값이어야 한다. 같은 종목의 시가총액이 화면마다
    # 다르면 어느 쪽을 믿어야 할지 알 수 없다.
    market_cap = us_universe.common_market_caps().get(company.cik) or price * Decimal(shares)

    eps = bps = dps = None
    per = pbr = dividend_yield = None
    per_note = pbr_note = dividend_note = None
    fiscal_year = period_end = None

    if financial is None:
        per_note = pbr_note = dividend_note = "재무 자료를 아직 받지 못했습니다."
    else:
        fiscal_year = financial.fiscal_year
        period_end = financial.period_end

        income = financial.net_income
        if income is None:
            per_note = "순이익 계정을 찾지 못했습니다."
        elif income <= 0:
            per_note = "적자라 PER 을 내지 않습니다."
        else:
            eps = (Decimal(income) / Decimal(shares)).quantize(CENT)
            per = (market_cap / Decimal(income)).quantize(CENT)

        equity = financial.total_equity
        if equity is None:
            pbr_note = "자본 계정을 찾지 못했습니다."
        elif equity <= 0:
            pbr_note = "자본잠식이라 PBR 을 내지 않습니다."
        else:
            bps = (Decimal(equity) / Decimal(shares)).quantize(CENT)
            pbr = (market_cap / Decimal(equity)).quantize(CENT)

        if financial.dps is None:
            dividend_note = f"{financial.fiscal_year} 회계연도에 주당배당금 공시가 없습니다."
        else:
            dps = Decimal(str(financial.dps))
            dividend_yield = (dps / price * 100).quantize(CENT)

    return UsValuation(
        ticker=ticker,
        name=company.name,
        price=price,
        shares_outstanding=shares,
        shares_as_of=shares_as_of,
        market_cap=market_cap,
        fiscal_year=fiscal_year,
        period_end=period_end,
        eps=eps,
        bps=bps,
        dps=dps,
        per=per,
        pbr=pbr,
        dividend_yield=dividend_yield,
        per_note=per_note,
        pbr_note=pbr_note,
        dividend_note=dividend_note,
    )


# ====================================================================== 미국 — 여러 종목
#
# 동종업계 비교가 쓴다. 국내 `screen_rows` 와 계산은 같고 **주가를 구하는 길이 다르다.**
#
# 국내에는 KRX 확정 종가라는 물러설 자리가 있어 모든 종목의 주가를 안다. 미국은 폴러가
# 들고 있는 것뿐이라, 비교할 종목들을 먼저 등록해 두고 값이 오기를 기다려야 한다
# (`routers/us_stocks.py`). 끝내 못 받은 종목은 지표를 비운 채 이름만 나온다 —
# 목록에서 통째로 빼면 "그 회사가 동종업계에 없다"로 잘못 읽힌다.


@dataclass(frozen=True)
class UsScreenRow:
    ticker: str
    name: str
    price: Decimal | None
    market_cap: Decimal | None
    fiscal_year: int | None
    per: Decimal | None
    pbr: Decimal | None
    roe: Decimal | None
    # 국내 `ScreenRow` 와 자리를 맞춘다. 스크리너의 '고배당' 조건이 이 값을 쓴다.
    # 국내는 DART 배당 공시를 따로 받아 두지만 미국은 10-K 재무에 주당배당금(dps)이
    # 함께 들어 있어 같은 표에서 나온다.
    dividend_yield: Decimal | None
    revenue_growth: Decimal | None


def us_screen_rows(tickers: list[str], *, prefer_live: bool = True) -> list[UsScreenRow]:
    """여러 미국 종목의 지표를 한꺼번에. 재무가 없는 종목은 빠진다.

    `prefer_live` — 폴러가 들고 있는 현재가를 먼저 볼지.

    **동종업계 비교는 참, 스크리너는 거짓이다.** 비교는 몇 종목뿐이라 값이 올 때까지
    기다릴 수 있고 새 값일수록 좋다. 스크리너는 수백 줄을 **나란히 놓고 견주는**
    화면이라 그럴 수 없다 — 어떤 줄은 방금 체결가, 어떤 줄은 어젯밤 종가면 PER 을
    같은 자로 잰 것이 아니게 된다. 국내가 KRX 확정 종가로 통일하는 것과 같은 이유다.
    """
    from app.models.us_company import SecCompany, SecFinancial

    if not tickers:
        return []

    with get_session() as session:
        companies = list(
            session.execute(
                select(SecCompany).where(SecCompany.ticker.in_(tickers))
            ).scalars()
        )
        if not companies:
            return []

        ciks = [c.cik for c in companies]
        latest: dict[str, SecFinancial] = {}
        by_year: dict[tuple[str, int], SecFinancial] = {}
        for row in session.execute(
            select(SecFinancial)
            .where(SecFinancial.cik.in_(ciks))
            .order_by(SecFinancial.fiscal_year.desc())
        ).scalars():
            latest.setdefault(row.cik, row)
            by_year[(row.cik, row.fiscal_year)] = row

    # 폴러가 마침 들고 있는 값이 있으면 그것이 가장 새것이다. 없으면 미리 받아 둔
    # 종가로 물러선다(`us_universe.refresh_closes`). 스크리너가 수백 종목을 폴러에
    # 등록하지 않아도 지표가 나오게 하려는 것이다 — 등록하면 웹소켓 구독 한도를
    # 스크리너가 먹어 치워 사용자가 보던 종목이 실시간에서 밀려난다.
    prices = poller.snapshot(tickers)
    # 보통주가 둘 이상인 회사만 담겨 온다. 그런 회사는 대표 티커 하나로 시가총액을
    # 낼 수 없다 — 버크셔는 A주만 세면 3분의 1이다. 293곳 중 한 곳뿐이라
    # 나머지는 아래 기존 계산을 그대로 지난다.
    multi_class = us_universe.common_market_caps()

    out: list[UsScreenRow] = []
    for company in companies:
        financial = latest.get(company.cik)
        if financial is None:
            continue

        cached = prices.get(company.ticker)
        price = cached.last_price if cached else company.last_close
        shares = us_shares(company)
        market_cap = multi_class.get(company.cik)
        if market_cap is None:
            market_cap = price * Decimal(shares) if price is not None and shares else None

        # us-gaap 은 이미 지배주주 기준이다(`NetIncomeLoss` 가 모회사 몫).
        income = financial.net_income
        equity = financial.total_equity
        previous = by_year.get((company.cik, financial.fiscal_year - 1))

        out.append(
            UsScreenRow(
                ticker=company.ticker,
                name=company.name,
                price=price,
                market_cap=market_cap,
                fiscal_year=financial.fiscal_year,
                per=(
                    (market_cap / Decimal(income)).quantize(CENT)
                    if market_cap is not None and income and income > 0
                    else None
                ),
                pbr=(
                    (market_cap / Decimal(equity)).quantize(CENT)
                    if market_cap is not None and equity and equity > 0
                    else None
                ),
                roe=_percent(income, equity) if equity and equity > 0 else None,
                # 주당배당금 ÷ 주가. `compute_us` 와 같은 식이어야 상세 화면과
                # 목록에서 같은 종목의 배당수익률이 다르게 보이지 않는다.
                dividend_yield=(
                    (Decimal(str(financial.dps)) / price * 100).quantize(CENT)
                    if financial.dps is not None and price is not None and price > 0
                    else None
                ),
                revenue_growth=(
                    _percent(financial.revenue - previous.revenue, previous.revenue)
                    if previous is not None
                    and financial.revenue is not None
                    and previous.revenue is not None
                    and previous.revenue > 0
                    else None
                ),
            )
        )
    return out
