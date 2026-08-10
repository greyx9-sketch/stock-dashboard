"""국내 주식 조회 엔드포인트.

DB 에 쌓아 둔 KRX 확정 종가를 읽어 준다. 외부 API 를 부르는 것은 현재가 하나뿐이고,
나머지는 전부 로컬 DB 조회라 빠르다.

경로 함수를 `async def` 가 아닌 `def` 로 둔 곳은 의도된 것이다. FastAPI 는 동기 함수를
별도 스레드에서 돌리므로, 동기 SQLAlchemy 를 써도 서버 전체가 멈추지 않는다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.models.base import get_session
from app.models.quote import KrxDailyQuote

router = APIRouter(prefix="/api/stocks", tags=["국내 주식"])

# 목록 정렬 기준. 사용자가 임의 컬럼을 넣지 못하도록 화이트리스트로 묶는다.
SORT_COLUMNS = {
    "market_cap": KrxDailyQuote.market_cap,
    "trade_value": KrxDailyQuote.trade_value,
    "volume": KrxDailyQuote.volume,
    "change_rate": KrxDailyQuote.change_rate,
    "close": KrxDailyQuote.close,
}

SortKey = Literal["market_cap", "trade_value", "volume", "change_rate", "close"]
MarketFilter = Literal["KOSPI", "KOSDAQ", "KONEX"]


class QuoteOut(BaseModel):
    """확정 시세 한 줄."""

    trade_date: str = Field(description="거래일 (YYYY-MM-DD)")
    symbol: str = Field(description="단축코드 6자리")
    name: str
    market: str = Field(description="KOSPI / KOSDAQ / KONEX")
    close: int = Field(description="정규장 확정 종가 (원)")
    change: int = Field(description="전일 대비 (원)")
    change_rate: Decimal = Field(description="등락률 (%)")
    open: int
    high: int
    low: int
    volume: int = Field(description="거래량 (주)")
    trade_value: int = Field(description="거래대금 (원)")
    market_cap: int = Field(description="시가총액 (원)")


class PricePoint(BaseModel):
    """차트용 최소 단위. 값이 많으므로 필드를 줄였다."""

    trade_date: str
    close: int
    open: int
    high: int
    low: int
    volume: int
    change_rate: Decimal


def _to_quote_out(row: KrxDailyQuote) -> QuoteOut:
    return QuoteOut(
        trade_date=row.trade_date,
        symbol=row.symbol,
        name=row.name,
        market=row.market,
        close=row.close,
        change=row.change,
        change_rate=row.change_rate,
        open=row.open,
        high=row.high,
        low=row.low,
        volume=row.volume,
        trade_value=row.trade_value,
        market_cap=row.market_cap,
    )


def _latest_trade_date(session) -> str | None:  # noqa: ANN001
    """DB 에 들어 있는 가장 최근 거래일."""
    return session.execute(select(func.max(KrxDailyQuote.trade_date))).scalar_one_or_none()


@router.get("", summary="종목 목록 (최신 거래일 기준)")
def list_stocks(
    limit: int = Query(50, ge=1, le=500, description="가져올 종목 수"),
    sort: SortKey = Query("market_cap", description="정렬 기준"),
    market: MarketFilter | None = Query(None, description="시장 필터. 비우면 전체"),
    trade_date: str | None = Query(
        None, description="조회할 거래일 (YYYY-MM-DD). 비우면 가장 최근 거래일"
    ),
) -> list[QuoteOut]:
    """한 거래일의 종목을 정렬해 돌려준다. 대시보드 첫 화면의 목록이 이것이다."""
    with get_session() as session:
        target_date = trade_date or _latest_trade_date(session)
        if target_date is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "DB 에 시세가 없습니다. "
                    "먼저 `python backend/scripts/ingest_krx.py` 로 확정 종가를 받아 주세요."
                ),
            )

        stmt = select(KrxDailyQuote).where(KrxDailyQuote.trade_date == target_date)
        if market:
            stmt = stmt.where(KrxDailyQuote.market == market)
        stmt = stmt.order_by(SORT_COLUMNS[sort].desc()).limit(limit)

        return [_to_quote_out(row) for row in session.execute(stmt).scalars()]


@router.get("/search", summary="종목 이름·코드로 찾기")
def search_stocks(
    q: str = Query(..., min_length=1, max_length=40, description="종목명 일부 또는 코드"),
    limit: int = Query(20, ge=1, le=100),
) -> list[QuoteOut]:
    """가장 최근 거래일 기준으로 이름이나 코드가 맞는 종목을 찾는다."""
    with get_session() as session:
        target_date = _latest_trade_date(session)
        if target_date is None:
            raise HTTPException(status_code=503, detail="DB 에 시세가 없습니다.")

        keyword = q.strip()
        stmt = (
            select(KrxDailyQuote)
            .where(KrxDailyQuote.trade_date == target_date)
            .where(
                KrxDailyQuote.name.contains(keyword) | KrxDailyQuote.symbol.startswith(keyword)
            )
            # 이름이 짧을수록 검색어와 가까운 종목일 가능성이 높다. 그다음은 시총 순.
            .order_by(func.length(KrxDailyQuote.name), KrxDailyQuote.market_cap.desc())
            .limit(limit)
        )
        return [_to_quote_out(row) for row in session.execute(stmt).scalars()]


@router.get("/{symbol}", summary="종목 상세 (확정 시세)")
def get_stock(
    symbol: str = Path(description="단축코드 6자리 (예: 005930)", pattern=r"^\d{6}$"),
) -> QuoteOut:
    """이 종목의 가장 최근 확정 시세.

    현재가는 여기서 주지 않는다. `/api/prices` 가 폴러 캐시에서 준다.
    토스를 부르는 곳을 폴러 한 군데로 모아 두어야 호출 한도를 한 곳에서 통제할 수 있고,
    화면이 종목을 바꿀 때마다 외부 API 를 기다리는 일도 없어진다.
    """
    with get_session() as session:
        row = session.execute(
            select(KrxDailyQuote)
            .where(KrxDailyQuote.symbol == symbol)
            .order_by(KrxDailyQuote.trade_date.desc())
            .limit(1)
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{symbol}' 종목의 시세가 DB 에 없습니다. 코드 6자리를 확인해 주세요.",
        )

    return _to_quote_out(row)


@router.get("/{symbol}/daily", summary="종목 일별 시세 (차트용)")
def get_daily_prices(
    symbol: str = Path(description="단축코드 6자리", pattern=r"^\d{6}$"),
    days: int = Query(90, ge=2, le=2000, description="가져올 거래일 수"),
) -> list[PricePoint]:
    """일별 확정 시세를 **오래된 날부터** 돌려준다. 차트가 그대로 그릴 수 있는 순서다."""
    with get_session() as session:
        rows = list(
            session.execute(
                select(KrxDailyQuote)
                .where(KrxDailyQuote.symbol == symbol)
                .order_by(KrxDailyQuote.trade_date.desc())
                .limit(days)
            ).scalars()
        )

    if not rows:
        raise HTTPException(
            status_code=404, detail=f"'{symbol}' 종목의 시세가 DB 에 없습니다."
        )

    rows.reverse()
    return [
        PricePoint(
            trade_date=r.trade_date,
            close=r.close,
            open=r.open,
            high=r.high,
            low=r.low,
            volume=r.volume,
            change_rate=r.change_rate,
        )
        for r in rows
    ]
