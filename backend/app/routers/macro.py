"""매크로 스트립 엔드포인트.

화면 상단 띠 하나를 위한 경로 하나뿐이다. 국내·미국 화면이 같은 것을 쓴다.

한 지표를 못 받아도 **200 으로 돌려준다.** 500 을 내면 화면이 띠를 통째로 못 그리는데,
실제로는 나머지 여섯 개가 멀쩡한 경우가 대부분이다. 못 받은 것은 `errors` 에 담고
저장된 값을 `stale` 로 표시해 보낸다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services import macro

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/macro", tags=["매크로 지표"])


class MacroItemOut(BaseModel):
    code: str
    label: str
    value: str = Field(description="화면에 그대로 쓸 문자열. 반올림·쉼표가 적용돼 있다")
    unit: str = Field(description='"" / 원 / % / $')
    change_rate: str | None = Field(description="등락률(%). 없는 지표는 null")
    as_of: str = Field(description="기준 시각 또는 기준일")
    source: str
    note: str = Field(description="화면에 함께 밝혀야 하는 단서")
    stale: bool = Field(description="지금 못 받아 저장된 값을 보여주는 중")


class MacroStripOut(BaseModel):
    items: list[MacroItemOut]
    errors: list[str] = Field(
        description="못 받은 지표의 이유. 비어 있으면 전부 정상"
    )


@router.get("", summary="매크로 스트립")
async def get_macro() -> MacroStripOut:
    """상단 띠에 쓸 지표들.

    코스피·코스닥·S&P500(SPY)·원달러는 토스에서 실시간으로, 한국·미국 기준금리는
    `시황` 프로젝트 피드에서, WTI 유가는 FRED 에서 온다. 갱신 주기가 달라 서버가
    각각 캐시한다 — 화면은 그냥 주기적으로 부르면 된다.
    """
    strip = await macro.get_strip()
    if strip.errors:
        logger.warning("매크로 일부 실패: %s", "; ".join(strip.errors)[:400])
    return MacroStripOut(
        items=[MacroItemOut(**vars(i)) for i in strip.items],
        errors=strip.errors,
    )
