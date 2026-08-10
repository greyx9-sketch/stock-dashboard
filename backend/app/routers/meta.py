"""데이터 현황 엔드포인트.

화면 아래쪽에 "언제 기준 데이터인지"를 밝히기 위한 것이다. 확정 종가는 하루 늦게
올라오므로, 지금 보고 있는 숫자가 며칠 자 데이터인지 화면에 반드시 표시해야 한다.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.models.base import get_session
from app.models.quote import KrxDailyQuote
from app.services.scheduler import scheduler

router = APIRouter(prefix="/api/meta", tags=["데이터 현황"])


class CollectionStatus(BaseModel):
    """확정 종가 자동 수집이 어떻게 돌고 있는지."""

    next_run_at: str | None = Field(description="다음 자동 수집 예정 시각")
    running: bool = Field(description="지금 수집 중인가")
    last_run_at: str | None = Field(description="마지막 수집 시각")
    last_run_ok: bool | None = Field(description="마지막 수집이 성공했는가. 아직 없으면 없음")
    last_run_days: int = Field(description="마지막 수집이 새로 채운 거래일 수")
    last_run_rows: int = Field(description="마지막 수집이 저장한 행 수")
    last_error: str | None = Field(description="마지막 수집이 실패한 이유")


class DataStatus(BaseModel):
    """DB 에 무엇이 얼마나 들어 있는지."""

    latest_trade_date: str | None = Field(description="가장 최근 확정 거래일")
    oldest_trade_date: str | None = Field(description="가장 오래된 확정 거래일")
    trading_days: int = Field(description="저장된 거래일 수")
    symbols_on_latest: int = Field(description="가장 최근 거래일의 종목 수")
    total_rows: int = Field(description="저장된 전체 행 수")
    source: str = Field(description="데이터 출처")
    note: str = Field(description="이 데이터의 시간 특성에 대한 안내")
    collection: CollectionStatus = Field(description="자동 수집 상태")


@router.get("", summary="데이터 현황")
def get_status() -> DataStatus:
    """지금 화면이 보여주는 데이터가 언제 기준인지 알려준다."""
    with get_session() as session:
        latest = session.execute(select(func.max(KrxDailyQuote.trade_date))).scalar_one_or_none()
        oldest = session.execute(select(func.min(KrxDailyQuote.trade_date))).scalar_one_or_none()
        trading_days = session.execute(
            select(func.count(func.distinct(KrxDailyQuote.trade_date)))
        ).scalar_one()
        total_rows = session.execute(select(func.count()).select_from(KrxDailyQuote)).scalar_one()
        symbols_on_latest = (
            session.execute(
                select(func.count()).where(KrxDailyQuote.trade_date == latest)
            ).scalar_one()
            if latest
            else 0
        )

    last = scheduler.last_run
    next_run = scheduler.next_run_at

    return DataStatus(
        collection=CollectionStatus(
            next_run_at=next_run.isoformat() if next_run else None,
            running=scheduler.is_running,
            last_run_at=last.started_at.isoformat() if last else None,
            last_run_ok=last.ok if last else None,
            last_run_days=last.trading_days if last else 0,
            last_run_rows=last.rows if last else 0,
            last_error=last.error if last else None,
        ),
        latest_trade_date=latest,
        oldest_trade_date=oldest,
        trading_days=trading_days,
        symbols_on_latest=symbols_on_latest,
        total_rows=total_rows,
        source="공공데이터포털 — 금융위원회 주식시세정보 (KRX 정규장 확정 종가)",
        note=(
            "확정 종가는 다음 영업일 오후 1시 이후에 공개된다. "
            "따라서 최신 거래일이 오늘이나 어제가 아닌 것이 정상이다."
        ),
    )
