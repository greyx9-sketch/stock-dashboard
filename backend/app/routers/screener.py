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

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.services import universe as universe_service
from app.services import valuation as valuation_service

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
