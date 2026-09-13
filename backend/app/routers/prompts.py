"""AI 리서치 지시서 엔드포인트.

화면의 `공시·분석` 자리가 이것으로 바뀌었다. 우리가 직접 분석하지 않고, **분석에 필요한
모든 것을 담은 지시서**를 만들어 사람이 claude.ai 에 붙여넣게 한다.

**돈이 나가지 않는 경로다.** 여기서는 어떤 LLM 도 부르지 않는다 — DB 를 읽고 공시 목록을
받아 글자를 이어 붙일 뿐이다. 종목을 처음 열 때 재무·공시를 받느라 몇 초 걸릴 수는 있다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.services import research_prompt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["AI 리서치 지시서"])


class PresetOut(BaseModel):
    id: str
    label: str
    hint: str = Field(description="단추 아래 한 줄. 이걸 고르면 무엇을 시키는지")


class PromptOut(BaseModel):
    symbol: str
    name: str
    market: str = Field(description="KR / US")
    preset: str
    text: str = Field(description="그대로 복사해 붙여넣을 글")
    included: list[str] = Field(description="이 지시서에 담긴 것")
    missing: list[str] = Field(description="담지 못한 것. 조용히 비우지 않는다")


@router.get("/prompt-presets", summary="지시서 종류 목록")
def list_presets() -> list[PresetOut]:
    """어떤 보고서를 시킬 수 있는지. 자료 블록은 같고 시키는 일만 다르다."""
    return [
        PresetOut(id=key, label=spec["label"], hint=spec["hint"])
        for key, spec in research_prompt.PRESETS.items()
    ]


@router.get("/stocks/{symbol}/prompt", summary="국내 종목 리서치 지시서")
async def kr_prompt(
    symbol: str = Path(description="단축코드 6자리", pattern=r"^\d{6}$"),
    preset: str = Query(research_prompt.DEFAULT_PRESET, description="지시서 종류"),
) -> PromptOut:
    try:
        prompt = await research_prompt.build_kr(symbol, preset)
    except research_prompt.PromptError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PromptOut(**vars(prompt))


@router.get("/us/{ticker}/prompt", summary="미국 종목 리서치 지시서")
async def us_prompt(
    ticker: str = Path(description="티커", min_length=1, max_length=12),
    preset: str = Query(research_prompt.DEFAULT_PRESET, description="지시서 종류"),
) -> PromptOut:
    try:
        prompt = await research_prompt.build_us(ticker, preset)
    except research_prompt.PromptError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PromptOut(**vars(prompt))
