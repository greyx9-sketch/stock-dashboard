"""스크리너와 동종업계 비교. 기획서 5.4.

**미리 받아 둔 것만 본다.** 조건에 맞는 종목을 찾으려면 후보 전부의 지표를 이미 알고
있어야 하는데, 조회 시점에 수백 종목의 재무를 받아 오면 몇 분이 걸린다. 그래서
`services/universe.py` 가 하룻밤에 한 번 채워 두고 여기서는 DB 만 읽는다.

그래서 **몇 종목을 보고 있는지 반드시 함께 알린다.** "조건에 맞는 종목이 3개"와
"우리가 아는 300종목 중 3개"는 다른 말이다. 앞의 것으로 읽히면 시장 전체를 훑은 줄
알게 된다.

주가는 **KRX 확정 종가**로 통일한다 — 목록의 줄마다 기준 시점이 다르면 PER 을 나란히
비교할 수 없다. 어느 날 종가인지 응답에 담는다.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.services import universe as universe_service
from app.services import us_universe
from app.services import valuation as valuation_service
from app.services.price_poller import poller

router = APIRouter(prefix="/api/screener", tags=["기업 분석"])

SORTABLE = ("market_cap", "per", "pbr", "roe", "dividend_yield", "revenue_growth")


class ScreenRowOut(BaseModel):
    symbol: str
    name: str
    market: str
    price: int
    market_cap: int
    fiscal_year: int | None
    per: Decimal | None
    pbr: Decimal | None
    roe: Decimal | None = Field(description="자기자본이익률 (%) — 지배주주 기준")
    dividend_yield: Decimal | None
    revenue_growth: Decimal | None = Field(description="매출 증가율 (%) — 전년 대비")


class ScreenOut(BaseModel):
    trade_date: str = Field(description="주가 기준일 (KRX 확정 종가)")
    universe: int = Field(description="지표를 알고 있는 종목 수. 시장 전체가 아니다")
    matched: int = Field(description="조건에 맞은 종목 수")
    rows: list[ScreenRowOut]
    industry_code: str | None = Field(
        default=None, description="동종업계를 묶은 표준산업분류 코드(중분류)"
    )
    holding_company: bool = Field(
        default=False,
        description=(
            "지주회사로 분류된 종목인가. 참이면 사업 내용이 달라도 같은 업종으로 묶이므로 "
            "화면이 그 사정을 밝혀야 한다"
        ),
    )


def _to_out(row: valuation_service.ScreenRow) -> ScreenRowOut:
    return ScreenRowOut(**{k: v for k, v in vars(row).items() if k != "trade_date"})


def _sorted(rows: list, key: str, descending: bool) -> list:
    """정렬. **값이 없는 줄은 언제나 뒤로 보낸다.**

    `None` 을 0 으로 치면 적자 기업이 'PER 낮은 순' 맨 앞에 올라온다. 그건 싼 것이
    아니라 값을 낼 수 없는 것이다.
    """
    have = [r for r in rows if getattr(r, key) is not None]
    missing = [r for r in rows if getattr(r, key) is None]
    have.sort(key=lambda r: getattr(r, key), reverse=descending)
    return have + missing


@router.get("", summary="조건으로 종목 고르기")
def screen(
    per_max: float | None = Query(None, gt=0, description="PER 이 이 값 이하"),
    pbr_max: float | None = Query(None, gt=0, description="PBR 이 이 값 이하"),
    roe_min: float | None = Query(None, description="ROE 가 이 값 이상 (%)"),
    yield_min: float | None = Query(None, ge=0, description="배당수익률이 이 값 이상 (%)"),
    growth_min: float | None = Query(None, description="매출 증가율이 이 값 이상 (%)"),
    market: str | None = Query(None, description="KOSPI / KOSDAQ. 없으면 전체"),
    sort: str = Query("market_cap", description=" / ".join(SORTABLE)),
    desc: bool = Query(True, description="내림차순인가"),
    limit: int = Query(50, ge=1, le=300),
) -> ScreenOut:
    """조건에 맞는 종목을 고른다.

    조건을 하나도 주지 않으면 유니버스 전체가 시가총액 순으로 나온다.

    **값이 없는 종목은 그 조건에서 걸러진다.** 적자라 PER 이 없는 회사는 "PER 15 이하"에
    들어오지 않는다 — 값이 없는 것을 통과시키면 조건이 뜻을 잃는다.
    """
    if sort not in SORTABLE:
        raise HTTPException(status_code=422, detail=f"정렬 기준은 {', '.join(SORTABLE)} 중 하나입니다.")

    rows = valuation_service.screen_rows()
    if not rows:
        return ScreenOut(trade_date="", universe=0, matched=0, rows=[])

    trade_date = rows[0].trade_date
    universe = len(rows)

    def passes(row: valuation_service.ScreenRow) -> bool:
        if market and row.market != market:
            return False
        # 조건을 건 항목의 값이 없으면 뺀다. 통과시키면 "PER 15 이하"에 PER 없는 회사가
        # 섞여 조건이 뜻을 잃는다.
        for value, bound, at_most in (
            (row.per, per_max, True),
            (row.pbr, pbr_max, True),
            (row.roe, roe_min, False),
            (row.dividend_yield, yield_min, False),
            (row.revenue_growth, growth_min, False),
        ):
            if bound is None:
                continue
            if value is None:
                return False
            if at_most and value > Decimal(str(bound)):
                return False
            if not at_most and value < Decimal(str(bound)):
                return False
        return True

    matched = [r for r in rows if passes(r)]
    ordered = _sorted(matched, sort, desc)

    return ScreenOut(
        trade_date=trade_date,
        universe=universe,
        matched=len(matched),
        rows=[_to_out(r) for r in ordered[:limit]],
    )


# ====================================================================== 미국
#
# 국내와 조건도 정렬도 같지만 **응답을 따로 둔다.** 미국 줄에는 KOSPI/KOSDAQ 같은
# 시장 구분이 없고, 주가와 시가총액이 달러이며(국내는 원화 정수), KRX 확정 종가에
# 해당하는 기준일이 없다. 국내 모델에 억지로 끼우면 두 화면 모두 읽기 나빠진다.

# 폴러가 주가를 받아 올 때까지 기다리는 횟수와 간격. `routers/us_stocks.py` 와 같은 값이다.
US_WAIT_TRIES = 6
US_WAIT_SEC = 0.5

US_SORTABLE = ("market_cap", "per", "pbr", "roe", "dividend_yield", "revenue_growth")


class UsScreenRowOut(BaseModel):
    ticker: str
    name: str
    price: Decimal | None
    market_cap: Decimal | None
    fiscal_year: int | None
    per: Decimal | None
    pbr: Decimal | None
    roe: Decimal | None
    dividend_yield: Decimal | None
    revenue_growth: Decimal | None


class UsScreenOut(BaseModel):
    universe: int = Field(description="지표를 알고 있는 회사 수. 미국 시장 전체가 아니다")
    matched: int = Field(description="조건에 맞은 회사 수")
    priced: int = Field(
        description="그중 주가까지 받아 온 회사 수. 주가가 없으면 PER·PBR·시총이 빈다"
    )
    rows: list[UsScreenRowOut]


@router.get("/us", summary="조건으로 미국 종목 고르기")
async def screen_us(
    per_max: float | None = Query(None, gt=0, description="PER 이 이 값 이하"),
    pbr_max: float | None = Query(None, gt=0, description="PBR 이 이 값 이하"),
    roe_min: float | None = Query(None, description="ROE 가 이 값 이상 (%)"),
    yield_min: float | None = Query(None, ge=0, description="배당수익률이 이 값 이상 (%)"),
    growth_min: float | None = Query(None, description="매출 증가율이 이 값 이상 (%)"),
    sort: str = Query("market_cap", description=" / ".join(US_SORTABLE)),
    desc: bool = Query(True, description="내림차순인가"),
    limit: int = Query(50, ge=1, le=300),
) -> UsScreenOut:
    """조건에 맞는 미국 종목을 고른다. 국내(`/api/screener`)와 조건이 같다.

    **유니버스가 국내보다 훨씬 작다.** 국내는 KRX 확정 시세를 매일 통째로 받아 두므로
    시가총액 상위 300종목을 공짜로 고르지만, 미국은 회사 하나의 재무에 3~4MB 짜리
    응답이 필요해 거래대금 상위만 담아 둔다. 거기서 ETF 와 우선주·워런트를 걷어내면
    회사 단위로 몇십 개다(`services/us_universe.screen_universe`). 화면이 그 수를 밝힌다.

    **주가는 폴러가 들고 있는 것을 쓴다.** 유니버스를 등록하고 잠깐 기다렸다 답한다.
    끝내 못 받은 종목은 지표를 비운 채 이름만 나온다 — 목록에서 빼면 "조건에 맞는
    회사가 그것뿐"으로 잘못 읽힌다. 대신 몇 개가 주가까지 받아졌는지를 함께 알린다.
    """
    if sort not in US_SORTABLE:
        raise HTTPException(
            status_code=422, detail=f"정렬 기준은 {', '.join(US_SORTABLE)} 중 하나입니다."
        )

    tickers = us_universe.screen_universe()
    if not tickers:
        return UsScreenOut(universe=0, matched=0, priced=0, rows=[])

    poller.register(tickers)
    rows = valuation_service.us_screen_rows(tickers)
    for _ in range(US_WAIT_TRIES):
        if all(r.price is not None for r in rows):
            break
        await asyncio.sleep(US_WAIT_SEC)
        rows = valuation_service.us_screen_rows(tickers)

    def passes(row: valuation_service.UsScreenRow) -> bool:
        # 국내와 같은 규칙 — 조건을 건 항목의 값이 없으면 뺀다. 주가를 못 받아
        # PER 이 빈 종목도 "PER 15 이하"에는 들어오지 않는다.
        for value, bound, at_most in (
            (row.per, per_max, True),
            (row.pbr, pbr_max, True),
            (row.roe, roe_min, False),
            (row.dividend_yield, yield_min, False),
            (row.revenue_growth, growth_min, False),
        ):
            if bound is None:
                continue
            if value is None:
                return False
            if at_most and value > Decimal(str(bound)):
                return False
            if not at_most and value < Decimal(str(bound)):
                return False
        return True

    matched = [r for r in rows if passes(r)]
    ordered = _sorted(matched, sort, desc)

    return UsScreenOut(
        universe=len(rows),
        matched=len(matched),
        priced=sum(1 for r in rows if r.price is not None),
        rows=[UsScreenRowOut(**vars(r)) for r in ordered[:limit]],
    )


@router.get("/peers/{symbol}", summary="동종업계 비교")
def peers(
    symbol: str = Path(description="단축코드 6자리", pattern=r"^\d{6}$"),
    limit: int = Query(10, ge=1, le=30),
) -> ScreenOut:
    """같은 업종의 다른 종목을 시가총액 큰 순으로. **자기 자신을 맨 앞에 둔다.**

    업종은 DART 기업개황의 표준산업분류 코드로 묶는다. 업종을 아직 모르는 종목은 빈
    목록이 온다 — 아무 종목이나 '동종업계'라고 보여주느니 비워 둔다.
    """
    group = universe_service.peers(symbol, limit=limit)
    if not group:
        return ScreenOut(trade_date="", universe=0, matched=0, rows=[])

    rows = valuation_service.screen_rows([symbol, *group])
    if not rows:
        return ScreenOut(trade_date="", universe=0, matched=0, rows=[])

    # 자기 자신을 맨 앞에. 나머지는 시가총액 순이다.
    mine = [r for r in rows if r.symbol == symbol]
    others = _sorted([r for r in rows if r.symbol != symbol], "market_cap", True)
    ordered = mine + others

    return ScreenOut(
        trade_date=rows[0].trade_date,
        universe=len(rows),
        matched=len(rows),
        rows=[_to_out(r) for r in ordered],
        industry_code=universe_service.industry_group(symbol),
        holding_company=universe_service.is_holding_company(symbol),
    )
