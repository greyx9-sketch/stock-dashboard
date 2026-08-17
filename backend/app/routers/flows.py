"""수급 동향 엔드포인트 (국내 전용).

미국 종목에는 없다 — 토스가 국내(KR) 종목만 제공한다. 미국 티커로 부르면 502 가 아니라
404 를 돌려준다. 없는 기능을 서버 오류처럼 보이게 하지 않기 위해서다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.services import flows as flows_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stocks", tags=["국내 주식 — 수급"])


class InvestorDayOut(BaseModel):
    date: str
    individual: int | None = Field(description="개인 순매수 (주)")
    foreigner: int | None = Field(description="외국인 순매수 (주)")
    institution: int | None = Field(description="기관 순매수 (주)")


class MetricOut(BaseModel):
    label: str
    value: str = Field(description="화면에 그대로 쓸 문자열")
    unit: str
    as_of: str = Field(description="이 지표의 기준일. 자료마다 갱신 시각이 달라 서로 다를 수 있다")
    note: str


class FlowsOut(BaseModel):
    symbol: str
    investors: list[InvestorDayOut] = Field(description="최신 거래일부터")
    metrics: list[MetricOut]
    errors: list[str] = Field(description="못 받은 자료의 이유. 비어 있으면 전부 정상")


SYMBOL_PATH = Path(description="종목 코드 6자리 (예: 005930)", pattern=r"^\d{6}$")


@router.get("/{symbol}/flows", summary="수급 동향 (투자자별·공매도·신용·대차·프로그램)")
async def get_flows(
    symbol: str = SYMBOL_PATH,
    days: int = Query(
        flows_service.DEFAULT_DAYS,
        ge=1,
        le=flows_service.MAX_DAYS,
        description="투자자별 순매수를 볼 거래일 수",
    ),
) -> FlowsOut:
    """국내 종목의 수급 자료를 한 벌로 돌려준다.

    다섯 경로를 동시에 부르고 **실패한 것만 빼고** 돌려준다. 하나가 없다고 수급 블록
    전체가 사라지면 사용자는 기능이 고장 났다고 여긴다.

    **자료마다 기준일이 다를 수 있다.** 공매도·대차거래는 당일 18~19시에, 신용거래·투자자별은
    다음 영업일 04시에 갱신된다. 그래서 지표마다 `as_of` 를 따로 들고 있다.
    """
    result = await flows_service.get_flows(symbol, days=days)

    if result.is_empty:
        joined = " ".join(result.errors)
        # 없는 종목을 502(서버 오류)로 돌리면 원인을 잘못 짚게 된다. 토스가 그렇다고
        # 말해 주므로 그대로 404 로 옮긴다.
        if "stock-not-found" in joined:
            raise HTTPException(
                status_code=404,
                detail=f"'{symbol}' 종목을 찾을 수 없습니다. 국내 6자리 종목코드인지 확인해 주세요.",
            )
        raise HTTPException(
            status_code=502,
            detail=(
                "수급 자료를 받지 못했습니다.\n  "
                + "\n  ".join(result.errors[:3] or ["원인을 알 수 없습니다."])
            ),
        )

    if result.errors:
        logger.warning("수급 일부 실패 (%s): %s", symbol, "; ".join(result.errors)[:300])

    return FlowsOut(
        symbol=result.symbol,
        investors=[InvestorDayOut(**vars(d)) for d in result.investors],
        metrics=[MetricOut(**vars(m)) for m in result.metrics],
        errors=result.errors,
    )
