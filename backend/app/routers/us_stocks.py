"""미국 주식 조회 엔드포인트 (SEC EDGAR).

국내와 경로를 나눈 이유: 조회 열쇠가 다르고(종목코드 vs 티커), 회계 기준이 다르고,
통화가 다르다. 한 경로에 합치면 어느 규칙으로 읽어야 하는지 알 수 없는 응답이 나온다.

**모든 재무 수치는 XBRL 사실에서 직접 계산한다**(CLAUDE.md 절대 규칙 3).
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.clients.sec import SecClient, SecError, UsFiling
from app.clients.toss import TossClient, TossError
from app.models.us_company import SecFinancial
from app.models.us_quarterly import SecQuarterly
from app.services import sec_companies, sec_financials, sec_quarterly, us_universe
from app.services import valuation as valuation_service
from app.services.price_poller import poller

router = APIRouter(prefix="/api/us", tags=["미국 주식"])

# 회사 개요·공시는 SEC 를 그때그때 부른다. 같은 종목을 연달아 열 때만 재호출을 막는다.
CACHE_TTL_SEC = 300.0
_submissions_cache: dict[str, tuple[float, dict]] = {}

# 랭킹은 장중에 계속 바뀐다. 짧게만 캐시해 화면을 여러 번 열어도 토스를 반복해서 부르지 않게 한다.
RANKING_TTL_SEC = 60.0
_ranking_cache: dict[int, tuple[float, list]] = {}

# 10-K(연차)·10-Q(분기)·8-K(수시)가 실제로 읽을 가치가 있는 공시다.
# 나머지(폼 4 내부자 거래 등)는 국내 지분공시처럼 목록을 덮어 버린다.
KEY_FORMS = ("10-K", "10-K/A", "10-Q", "8-K")


class UsCompanyOut(BaseModel):
    ticker: str
    cik: str = Field(description="SEC 제출자 고유번호 (10자리)")
    name: str


class UsCompanyDetail(UsCompanyOut):
    exchange: str | None = Field(description="상장 거래소")
    industry: str | None = Field(description="SIC 업종 설명")
    fiscal_year_end: str | None = Field(description="결산월일 (MMDD)")
    website: str | None


class UsFilingOut(BaseModel):
    accession_no: str
    form: str = Field(description="10-K 연차 / 10-Q 분기 / 8-K 수시")
    filing_date: str
    report_date: str
    description: str
    viewer_url: str = Field(description="EDGAR 원문 주소")


class UsFinancialYear(BaseModel):
    fiscal_year: int = Field(description="회계연도")
    period_end: str = Field(
        description="회계연도 종료일. 미국은 12월 결산이 아닌 회사가 흔해 이 날짜를 함께 봐야 한다"
    )
    revenue: int | None
    gross_profit: int | None
    operating_income: int | None = Field(description="영업이익. 은행 등은 보고하지 않는다")
    net_income: int | None
    total_assets: int | None
    total_liabilities: int | None
    total_equity: int | None

    operating_margin: Decimal | None
    net_margin: Decimal | None
    revenue_growth: Decimal | None
    roe: Decimal | None
    debt_ratio: Decimal | None

    accession_no: str
    filed_date: str
    source_url: str


class UsFinancialsOut(BaseModel):
    ticker: str
    cik: str
    name: str
    currency: str
    years: list[UsFinancialYear] = Field(description="오래된 연도부터")


def _pct(numerator: int | None, denominator: int | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * 100).quantize(Decimal("0.01"))


def _growth(current: int | None, previous: int | None) -> Decimal | None:
    """전년 대비 증가율. 전년이 0 이하면 뜻을 잃으므로 계산하지 않는다."""
    if current is None or previous is None or previous <= 0:
        return None
    return ((Decimal(current) - Decimal(previous)) / Decimal(previous) * 100).quantize(
        Decimal("0.01")
    )


def _edgar_url(cik: str, accession_no: str) -> str:
    folder = accession_no.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{folder}/"


def _resolve(ticker: str):
    company = sec_companies.get_company(ticker)
    if company is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{ticker.upper()}' 티커를 SEC 목록에서 찾지 못했습니다.\n"
                "미국 상장사가 아니거나, 티커 매핑이 아직 받아지지 않았을 수 있습니다."
            ),
        )
    return company


async def _submissions(cik: str) -> dict:
    """회사 개요·공시 이력. 5분 캐시."""
    now = time.monotonic()
    cached = _submissions_cache.get(cik)
    if cached and now - cached[0] < CACHE_TTL_SEC:
        return cached[1]

    try:
        async with SecClient() as sec:
            data = await sec.get_submissions(cik)
    except SecError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        # config.require() — SEC_USER_AGENT 가 아직 없다.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _submissions_cache[cik] = (now, data)

    # 같은 응답에 업종(SIC)이 들어 있다. **공짜로 넓히는 자리다.**
    #
    # 유니버스 적재는 거래대금 상위 100종목만 훑으므로, 그 밖의 종목은 업종을 모른 채로
    # 남는다(KO 가 그랬다). 사용자가 종목을 열면 어차피 이 호출이 나가니 그때 채워 둔다.
    # 이미 알고 있으면 아무 일도 하지 않는다.
    us_universe.remember_industry(cik, data)
    return data


class UsListItem(BaseModel):
    """미국 종목 목록 한 줄. 시세는 토스, 이름·구분도 토스에서 온다."""

    symbol: str
    name: str = Field(description="한글명. 없으면 티커")
    english_name: str | None
    market: str | None = Field(description="NASDAQ / NYSE / AMEX")
    security_type: str | None = Field(description="STOCK / ETF")
    last_price: Decimal
    base_price: Decimal = Field(description="기준가 — 토스가 계산한 전일 종가")
    change: Decimal
    change_rate: Decimal = Field(description="등락률 (%)")
    trading_volume: int
    trading_amount: int = Field(description="거래대금 (원 환산)")
    currency: str


async def top_us_symbols(count: int) -> list[str]:
    """거래대금 상위 티커만. 야간 유니버스 적재가 쓴다.

    목록 엔드포인트와 달리 이름·시세를 붙이지 않는다 — 적재에는 티커만 있으면 되고,
    종목 정보를 또 받으면 호출만 늘어난다.
    """
    async with TossClient() as toss:
        data = await toss.get_rankings(market_country="US", count=count)
    return [r["symbol"] for r in (data.get("rankings") or []) if r.get("symbol")]


@router.get("/list", summary="미국 종목 목록 (거래대금 상위)")
async def list_us_stocks(
    limit: int = Query(50, ge=1, le=100, description="가져올 종목 수"),
) -> list[UsListItem]:
    """토스증권 거래대금 상위 랭킹으로 목록을 만든다.

    국내와 달리 KRX 확정 종가 같은 별도 기준가 소스가 없다. 대신 토스 랭킹이 기준가
    (`basePrice`)를 직접 내려주므로 그것을 그대로 쓴다 — 국내에서 랭킹 기준가가 앱 화면과
    일치하는 것을 이미 확인했다.

    ETF 가 상위권에 많이 올라온다(SOXL·QQQ 등). 걸러내지 않고 구분만 표시한다 —
    실제로 거래대금이 큰 것이 사실이고, 감추면 목록이 현실과 달라진다.
    """
    now = time.monotonic()
    cached = _ranking_cache.get(limit)
    if cached and now - cached[0] < RANKING_TTL_SEC:
        return cached[1]

    try:
        async with TossClient() as toss:
            data = await toss.get_rankings(market_country="US", count=limit)
            rows = data.get("rankings") or []
            symbols = [r["symbol"] for r in rows if r.get("symbol")]
            # 랭킹 응답에는 이름이 없다. 종목 정보를 따로 받아 붙인다.
            info = {s["symbol"]: s for s in (await toss.get_stocks(symbols) if symbols else [])}
    except TossError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    items: list[UsListItem] = []
    for row in rows:
        symbol = row.get("symbol")
        price = row.get("price") or {}
        if not symbol or price.get("lastPrice") is None:
            continue

        last = Decimal(str(price["lastPrice"]))
        base = Decimal(str(price.get("basePrice") or last))
        meta = info.get(symbol, {})

        items.append(
            UsListItem(
                symbol=symbol,
                name=meta.get("name") or symbol,
                english_name=meta.get("englishName"),
                market=meta.get("market"),
                security_type=meta.get("securityType"),
                last_price=last,
                base_price=base,
                change=last - base,
                # 토스는 등락률을 비율(0.0143)로 준다. 화면은 % 로 쓰므로 여기서 바꾼다.
                change_rate=(Decimal(str(price.get("changeRate") or 0)) * 100).quantize(
                    Decimal("0.01")
                ),
                trading_volume=int(row.get("tradingVolume") or 0),
                trading_amount=int(row.get("tradingAmount") or 0),
                currency=row.get("currency") or "USD",
            )
        )

    _ranking_cache[limit] = (now, items)
    return items


@router.get("/search", summary="미국 종목 검색")
def search_us(
    q: str = Query(..., min_length=1, max_length=40, description="티커 또는 회사명"),
    limit: int = Query(20, ge=1, le=100),
) -> list[UsCompanyOut]:
    """티커나 회사명으로 찾는다."""
    return [
        UsCompanyOut(ticker=c.ticker, cik=c.cik, name=c.name)
        for c in sec_companies.search(q, limit=limit)
    ]


@router.get("/{ticker}", summary="미국 기업 개요")
async def get_us_company(
    ticker: str = Path(description="티커 (예: AAPL)", pattern=r"^[A-Za-z0-9.\-]{1,12}$"),
) -> UsCompanyDetail:
    """회사 이름·거래소·업종·결산월."""
    company = _resolve(ticker)
    data = await _submissions(company.cik)
    exchanges = data.get("exchanges") or []

    return UsCompanyDetail(
        ticker=company.ticker,
        cik=company.cik,
        name=data.get("name") or company.name,
        exchange=exchanges[0] if exchanges else None,
        industry=data.get("sicDescription"),
        fiscal_year_end=data.get("fiscalYearEnd"),
        website=data.get("website") or None,
    )


@router.get("/{ticker}/filings", summary="미국 기업 공시")
async def get_us_filings(
    ticker: str = Path(description="티커 (예: AAPL)", pattern=r"^[A-Za-z0-9.\-]{1,12}$"),
    count: int = Query(20, ge=1, le=100),
    key_forms_only: bool = Query(
        True, description="10-K·10-Q·8-K 만 볼지. 끄면 내부자 거래(폼 4)까지 전부 나온다"
    ),
) -> list[UsFilingOut]:
    """공시를 최신순으로 돌려준다.

    기본값이 주요 서식만인 이유는 국내와 같다 — 폼 4(내부자 거래)가 목록을 덮어 버린다.
    """
    company = _resolve(ticker)
    data = await _submissions(company.cik)

    filings: list[UsFiling] = SecClient.parse_filings(
        data, forms=KEY_FORMS if key_forms_only else None, limit=count
    )
    return [
        UsFilingOut(
            accession_no=f.accession_no,
            form=f.form,
            filing_date=f.filing_date,
            report_date=f.report_date,
            description=f.description,
            viewer_url=f.viewer_url,
        )
        for f in filings
    ]


@router.get("/{ticker}/financials", summary="미국 기업 연간 재무 (10-K)")
async def get_us_financials(
    ticker: str = Path(description="티커 (예: AAPL)", pattern=r"^[A-Za-z0-9.\-]{1,12}$"),
    years: int = Query(6, ge=2, le=12),
) -> UsFinancialsOut:
    """10-K 기준 연간 재무를 **오래된 연도부터** 돌려준다.

    `fiscal_year` 는 회계연도가 대부분 걸쳐 있는 달력 연도로 붙인 이름이다. 회사가 스스로
    부르는 이름과 다를 수 있으므로(월마트는 2025년 1월 말 결산을 'FY2025' 라 부른다)
    `period_end` 를 반드시 함께 본다.
    """
    company = _resolve(ticker)

    try:
        await sec_financials.ensure_financials(company.cik, years=years)
    except SecError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    rows: list[SecFinancial] = sec_financials.load(company.cik, years=years)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{company.ticker}' 의 XBRL 재무를 찾지 못했습니다.\n"
                "10-K 를 내지 않는 외국 발행사(20-F 제출)이거나 신규 상장일 수 있습니다."
            ),
        )

    out: list[UsFinancialYear] = []
    for index, row in enumerate(rows):
        previous = rows[index - 1] if index > 0 else None
        out.append(
            UsFinancialYear(
                fiscal_year=row.fiscal_year,
                period_end=row.period_end,
                revenue=row.revenue,
                gross_profit=row.gross_profit,
                operating_income=row.operating_income,
                net_income=row.net_income,
                total_assets=row.total_assets,
                total_liabilities=row.total_liabilities,
                total_equity=row.total_equity,
                operating_margin=_pct(row.operating_income, row.revenue),
                net_margin=_pct(row.net_income, row.revenue),
                revenue_growth=_growth(row.revenue, previous.revenue if previous else None),
                roe=_pct(row.net_income, row.total_equity),
                debt_ratio=_pct(row.total_liabilities, row.total_equity),
                accession_no=row.accession_no,
                filed_date=row.filed_date,
                source_url=_edgar_url(company.cik, row.accession_no),
            )
        )

    return UsFinancialsOut(
        ticker=company.ticker,
        cik=company.cik,
        name=company.name,
        currency=rows[-1].currency,
        years=out,
    )


# ====================================================================== 밸류에이션


# 현재가를 기다리는 시간. 등록하면 폴러가 곧바로 깨어나므로 길 필요가 없다.
# 그래도 안 오면(장 마감으로 폴링이 느슨하거나 토스가 늦거나) 안내 문구로 답한다.
VALUATION_WAIT_TRIES = 6
VALUATION_WAIT_SEC = 0.5


class UsValuationOut(BaseModel):
    """미국 종목의 PER · PBR · 배당수익률.

    국내와 계산은 같다. 다른 것은 **주식수의 기준일이 재무보다 앞선다**는 점이다 —
    SEC 가 주는 발행주식수는 가장 최근 제출 서류 표지의 수량이라, 2025 회계연도 재무에
    2026년 주식수가 붙는다. 시가총액은 그것이 맞지만 화면에 기준일을 밝힌다.
    """

    ticker: str
    name: str

    price: Decimal = Field(description="토스 현재가 (USD)")
    shares_outstanding: int
    shares_as_of: str | None = Field(description="주식수 기준일. 재무 기간과 다르다")
    market_cap: Decimal

    fiscal_year: int | None
    period_end: str | None = Field(description="그 회계연도 종료일")

    eps: Decimal | None
    bps: Decimal | None
    dps: Decimal | None = Field(description="주당 현금배당금 (USD). 그 해 선언 기준")

    per: Decimal | None
    pbr: Decimal | None
    dividend_yield: Decimal | None

    per_note: str | None
    pbr_note: str | None
    dividend_note: str | None


@router.get("/{ticker}/valuation", summary="미국 밸류에이션 (PER·PBR·배당수익률)")
async def get_us_valuation(
    ticker: str = Path(description="티커 (예: AAPL)"),
) -> UsValuationOut:
    """**현재가를 받지 못하면 계산하지 않는다.**

    국내에는 KRX 확정 종가라는 물러설 자리가 있지만 미국은 토스 현재가뿐이다. 옛 값으로
    PER 을 내면 그것이 언제 기준인지 밝힐 방법이 없다.
    """
    symbol = ticker.strip().upper()
    company = sec_companies.get_company(symbol)
    if company is None:
        raise HTTPException(status_code=404, detail=f"'{symbol}' 을 SEC 목록에서 찾지 못했습니다.")

    try:
        await sec_financials.ensure_financials(company.cik, years=2)
    except Exception as exc:  # SEC 가 느리거나 막혀도 화면 전체를 죽이지 않는다
        raise HTTPException(status_code=502, detail=f"SEC 조회에 실패했습니다 — {exc}") from exc

    # 현재가는 폴러가 들고 있다. 처음 보는 종목이면 아직 없으므로 등록하고 **잠깐
    # 기다린다** — 등록하면 폴러가 즉시 깨어나 받아 오고, 대개 1초 안에 들어온다.
    #
    # 기다리지 않으면 종목을 처음 열 때마다 "낼 수 없습니다"가 뜨고 새로고침해야 나온다.
    # 실제로 그랬다(2026-08-25 서버 확인: 첫 호출 실패, 두 번째 성공).
    poller.register([symbol])
    result = valuation_service.compute_us(symbol)
    for _ in range(VALUATION_WAIT_TRIES):
        if result is not None:
            break
        await asyncio.sleep(VALUATION_WAIT_SEC)
        result = valuation_service.compute_us(symbol)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{symbol}' 의 밸류에이션을 낼 수 없습니다.\n"
                "현재가나 발행주식수를 아직 받지 못했습니다. 잠시 뒤 다시 열어 보세요."
            ),
        )
    return UsValuationOut(**vars(result))


# ====================================================================== 분기 재무 (10-Q)


class UsQuarterOut(BaseModel):
    """한 분기의 재무. 국내와 같은 모양이다 — 화면이 같은 표를 쓴다."""

    fiscal_year: int
    quarter: int = Field(description="1~4")
    label: str = Field(description="화면에 쓸 이름 (예: FY2026 1Q)")
    period_end: str | None = Field(
        description="분기 종료일. **회계연도가 회사마다 달라 반드시 함께 본다**"
    )
    derived: bool = Field(
        description="4분기의 3개월 손익만 참 — 10-K 에서 3분기 누적을 뺀 계산값이다"
    )

    revenue: int | None
    gross_profit: int | None
    operating_income: int | None
    net_income: int | None

    revenue_cum: int | None
    gross_profit_cum: int | None
    operating_income_cum: int | None
    net_income_cum: int | None

    total_assets: int | None
    total_liabilities: int | None
    total_equity: int | None

    operating_margin: Decimal | None = Field(description="영업이익률 (%) — 3개월 기준")
    net_margin: Decimal | None = Field(description="순이익률 (%) — 3개월 기준")
    operating_margin_cum: Decimal | None
    net_margin_cum: Decimal | None

    revenue_yoy: Decimal | None = Field(description="매출 증가율 (%) — 전년 동분기 대비")
    operating_income_yoy: Decimal | None
    revenue_cum_yoy: Decimal | None
    operating_income_cum_yoy: Decimal | None


class UsQuarterlyOut(BaseModel):
    ticker: str
    cik: str
    name: str
    currency: str
    quarters: list[UsQuarterOut] = Field(description="오래된 분기부터")


def _us_pct(numerator: int | None, denominator: int | None) -> Decimal | None:
    if numerator is None or not denominator:
        return None
    return (Decimal(numerator) / Decimal(denominator) * 100).quantize(Decimal("0.01"))


def _us_growth(current: int | None, previous: int | None) -> Decimal | None:
    """전년 동분기 대비 증가율. 전년이 적자면 뜻을 잃으므로 내지 않는다."""
    if current is None or previous is None or previous <= 0:
        return None
    return ((Decimal(current) - Decimal(previous)) / Decimal(previous) * 100).quantize(
        Decimal("0.01")
    )


def _us_minus(total: int | None, part: int | None) -> int | None:
    if total is None or part is None:
        return None
    return total - part


def _us_quarter_dict(row: SecQuarterly) -> dict:
    return {
        "fiscal_year": row.fiscal_year,
        "quarter": row.quarter,
        "period_end": row.period_end or None,
        "derived": False,
        "revenue": row.revenue,
        "gross_profit": row.gross_profit,
        "operating_income": row.operating_income,
        "net_income": row.net_income,
        "revenue_cum": row.revenue_cum,
        "gross_profit_cum": row.gross_profit_cum,
        "operating_income_cum": row.operating_income_cum,
        "net_income_cum": row.net_income_cum,
        "total_assets": row.total_assets,
        "total_liabilities": row.total_liabilities,
        "total_equity": row.total_equity,
    }


def _us_q4(annual: SecFinancial, q3: dict | None) -> dict | None:
    """4분기 한 행. 미국도 4분기를 따로 내지 않고 10-K 가 그 자리를 대신한다.

    - **3개월 손익** = 연간 − 3분기 누적. 이것만 계산값이다.
    - **누적 손익** = 연간 그 자체.
    - **재무상태** = 10-K 의 기말 잔액. 계산이 아니라 원값이다.

    3분기 누적이 없으면 만들지 않는다 — 연간값을 4분기인 척 보여주면 네 배 부풀려진다.
    """
    if q3 is None:
        return None

    three_month = {
        "revenue": _us_minus(annual.revenue, q3["revenue_cum"]),
        "gross_profit": _us_minus(annual.gross_profit, q3["gross_profit_cum"]),
        "operating_income": _us_minus(annual.operating_income, q3["operating_income_cum"]),
        "net_income": _us_minus(annual.net_income, q3["net_income_cum"]),
    }
    if all(v is None for v in three_month.values()):
        return None

    return {
        "fiscal_year": annual.fiscal_year,
        "quarter": 4,
        "period_end": annual.period_end or None,
        "derived": True,
        **three_month,
        "revenue_cum": annual.revenue,
        "gross_profit_cum": annual.gross_profit,
        "operating_income_cum": annual.operating_income,
        "net_income_cum": annual.net_income,
        "total_assets": annual.total_assets,
        "total_liabilities": annual.total_liabilities,
        "total_equity": annual.total_equity,
    }


def _to_us_quarter(point: dict, year_ago: dict | None) -> UsQuarterOut:
    prev = year_ago or {}
    return UsQuarterOut(
        **{k: point[k] for k in (
            "fiscal_year", "quarter", "period_end", "derived",
            "revenue", "gross_profit", "operating_income", "net_income",
            "revenue_cum", "gross_profit_cum", "operating_income_cum", "net_income_cum",
            "total_assets", "total_liabilities", "total_equity",
        )},
        label=f"FY{point['fiscal_year']} {point['quarter']}Q",
        operating_margin=_us_pct(point["operating_income"], point["revenue"]),
        net_margin=_us_pct(point["net_income"], point["revenue"]),
        operating_margin_cum=_us_pct(point["operating_income_cum"], point["revenue_cum"]),
        net_margin_cum=_us_pct(point["net_income_cum"], point["revenue_cum"]),
        # 전분기가 아니라 전년 동분기와 견준다 — 분기 실적은 계절을 심하게 탄다.
        revenue_yoy=_us_growth(point["revenue"], prev.get("revenue")),
        operating_income_yoy=_us_growth(point["operating_income"], prev.get("operating_income")),
        revenue_cum_yoy=_us_growth(point["revenue_cum"], prev.get("revenue_cum")),
        operating_income_cum_yoy=_us_growth(
            point["operating_income_cum"], prev.get("operating_income_cum")
        ),
    )


@router.get("/{ticker}/financials/quarterly", summary="미국 분기 재무 (10-Q)")
async def get_us_quarterly(
    ticker: str = Path(description="티커 (예: AAPL)"),
    quarters: int = Query(12, ge=4, le=20, description="가져올 분기 수"),
) -> UsQuarterlyOut:
    """분기 재무를 **오래된 분기부터** 돌려준다. 국내와 같은 모양이다.

    한 분기마다 **당분기 3개월**과 **회계연도 초부터 누적**을 함께 담는다. 둘 다 10-Q 에
    실린 원값이다.

    **4분기는 10-Q 가 없다.** 10-K 가 그 자리를 대신하므로 4분기의 3개월 손익만
    `연간 − 3분기 누적`으로 계산해 채우고 `derived` 를 참으로 표시한다.

    **회계연도가 회사마다 다르다.** 애플 FY2026 1분기는 2025년 12월에 끝나고,
    마이크로소프트 FY2026 1분기는 2025년 9월에 끝난다. `period_end` 를 함께 본다.
    """
    symbol = ticker.strip().upper()
    company = sec_companies.get_company(symbol)
    if company is None:
        raise HTTPException(status_code=404, detail=f"'{symbol}' 을 SEC 목록에서 찾지 못했습니다.")

    try:
        # 4분기를 만들려면 연간도 있어야 한다.
        await sec_financials.ensure_financials(company.cik, years=4)
        await sec_quarterly.ensure_quarters(company.cik)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SEC 조회에 실패했습니다 — {exc}") from exc

    rows = sec_quarterly.load(company.cik, limit=quarters)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{symbol}' 의 분기 재무를 찾지 못했습니다.\n"
                "10-Q 를 내지 않는 종목(ETF·DR 등)일 수 있습니다."
            ),
        )

    points = [_us_quarter_dict(r) for r in rows]

    by_period = {(p["fiscal_year"], p["quarter"]): p for p in points}
    for annual in sec_financials.load(company.cik, years=6):
        if (annual.fiscal_year, 4) in by_period:
            continue
        made = _us_q4(annual, by_period.get((annual.fiscal_year, 3)))
        if made is not None:
            points.append(made)

    points.sort(key=lambda p: (p["fiscal_year"], p["quarter"]))

    # 전년 동분기는 **자르기 전** 목록에서 찾는다 — 화면에 안 보이는 분기도 비교
    # 대상으로는 쓸 수 있어야 맨 앞 분기에도 증가율이 나온다.
    lookup = {(p["fiscal_year"], p["quarter"]): p for p in points}
    points = points[-quarters:]

    return UsQuarterlyOut(
        ticker=symbol,
        cik=company.cik,
        name=company.name,
        currency="USD",
        quarters=[
            _to_us_quarter(p, lookup.get((p["fiscal_year"] - 1, p["quarter"]))) for p in points
        ],
    )


# ====================================================================== 동종업계 비교


class UsPeerRow(BaseModel):
    ticker: str
    name: str
    price: Decimal | None
    market_cap: Decimal | None
    fiscal_year: int | None
    per: Decimal | None
    pbr: Decimal | None
    roe: Decimal | None = Field(description="자기자본이익률 (%)")
    revenue_growth: Decimal | None = Field(description="매출 증가율 (%) — 전년 대비")


class UsPeersOut(BaseModel):
    ticker: str
    sic: str | None = Field(description="SEC 표준산업분류 코드")
    sic_description: str | None = Field(description="업종 이름. SEC 가 함께 준다")
    universe: int = Field(
        description="지표를 아는 종목 수. 미국은 토스 거래대금 상위만 담아 둔다"
    )
    rows: list[UsPeerRow] = Field(description="자기 자신이 맨 앞, 나머지는 시가총액 순")


@router.get("/{ticker}/peers", summary="미국 동종업계 비교")
async def get_us_peers(
    ticker: str = Path(description="티커 (예: NVDA)"),
    limit: int = Query(10, ge=1, le=30),
) -> UsPeersOut:
    """같은 SIC 의 종목을 나란히 놓는다.

    **미리 받아 둔 종목 안에서만 나온다.** 미국은 회사 하나의 재무를 받는 데 3~4MB 짜리
    응답이 필요해서, 토스 거래대금 상위 100종목만 담아 둔다(`services/us_universe.py`).
    화면이 그 사실을 밝힌다.

    주가는 폴러가 들고 있는 것을 쓴다. 비교 대상을 등록하고 잠깐 기다렸다 답한다 —
    끝내 못 받은 종목은 지표를 비운 채 이름만 나온다. 목록에서 통째로 빼면 "그 회사가
    동종업계에 없다"로 잘못 읽힌다.
    """
    symbol = ticker.strip().upper()
    company = sec_companies.get_company(symbol)
    if company is None:
        raise HTTPException(status_code=404, detail=f"'{symbol}' 을 SEC 목록에서 찾지 못했습니다.")

    sic, sic_name = us_universe.industry_of(symbol)
    group = us_universe.peers(symbol, limit=limit)
    if not sic or not group:
        return UsPeersOut(ticker=symbol, sic=sic, sic_description=sic_name, universe=0, rows=[])

    wanted = [symbol, *group]
    poller.register(wanted)
    rows = valuation_service.us_screen_rows(wanted)
    for _ in range(VALUATION_WAIT_TRIES):
        if all(r.price is not None for r in rows):
            break
        await asyncio.sleep(VALUATION_WAIT_SEC)
        rows = valuation_service.us_screen_rows(wanted)

    # 자기 자신을 맨 앞에. 나머지는 시가총액 순이고, 시총을 모르는 줄은 뒤로 보낸다.
    mine = [r for r in rows if r.ticker == symbol]
    others = [r for r in rows if r.ticker != symbol]
    known = sorted(
        [r for r in others if r.market_cap is not None], key=lambda r: r.market_cap, reverse=True
    )
    unknown = [r for r in others if r.market_cap is None]

    return UsPeersOut(
        ticker=symbol,
        sic=sic,
        sic_description=sic_name,
        universe=len(rows),
        rows=[UsPeerRow(**vars(r)) for r in (mine + known + unknown)],
    )
