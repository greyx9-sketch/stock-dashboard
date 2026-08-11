"""미국 주식 조회 엔드포인트 (SEC EDGAR).

국내와 경로를 나눈 이유: 조회 열쇠가 다르고(종목코드 vs 티커), 회계 기준이 다르고,
통화가 다르다. 한 경로에 합치면 어느 규칙으로 읽어야 하는지 알 수 없는 응답이 나온다.

**모든 재무 수치는 XBRL 사실에서 직접 계산한다**(CLAUDE.md 절대 규칙 3).
"""

from __future__ import annotations

import time
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.clients.sec import SecClient, SecError, UsFiling
from app.clients.toss import TossClient, TossError
from app.models.us_company import SecFinancial
from app.services import sec_companies, sec_financials

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
