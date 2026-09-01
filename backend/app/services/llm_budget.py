"""LLM 호출의 비용 상한 — 국내·미국이 함께 쓴다.

미국 10-K 분석(`tenk_analysis.py`)과 국내 사업보고서 분석(`dart_analysis.py`)이 각자
하루 상한을 세면, 설정한 "하루 20건" 이 실제로는 40건이 된다. 상한은 지갑 기준이지
시장 기준이 아니므로 여기서 한 번에 센다.

동시 실행 잠금도 여기 있다. 두 시장에서 동시에 호출이 나가면 1 OCPU 서버가 눌리고,
캐시 확인과 저장 사이의 틈으로 같은 문서가 두 번 분석될 수 있다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.config import get_settings
from app.models.base import get_session
from app.models.dart_analysis import DartAnalysis
from app.models.us_analysis import SecAnalysis

# Sonnet 5 정가(100만 토큰당). 도입가 기간에는 실제 청구가 이보다 적다.
# 적게 추정하는 쪽이 위험하므로 일부러 비싼 쪽으로 잡는다.
PRICE_INPUT_PER_MTOK_USD = 3.0
PRICE_OUTPUT_PER_MTOK_USD = 15.0

# Batch API 는 모든 토큰이 반값이다. 자동 분석이 이 길로 간다(`analysis_batch.py`).
BATCH_DISCOUNT = 0.5

# 두 시장이 함께 쓰는 잠금. 한 번에 한 건만 분석한다.
call_lock = asyncio.Lock()


class BudgetExceeded(Exception):
    """하루 상한에 도달. 메시지를 그대로 화면에 보여줄 수 있게 쓴다."""


def cost_micro_usd(input_tokens: int, output_tokens: int, *, batch: bool = False) -> int:
    """달러는 소수라 정수(100만분의 1달러)로 다룬다. float 로 두면 합계가 어긋난다.

    `batch=True` 는 Batch API 로 처리된 건이다 — **모든 토큰이 반값**이다
    (입력·출력·캐시 전부). 밤에 도는 자동 분석이 이쪽을 쓴다.
    """
    dollars = (
        input_tokens * PRICE_INPUT_PER_MTOK_USD + output_tokens * PRICE_OUTPUT_PER_MTOK_USD
    ) / 1_000_000
    if batch:
        dollars *= BATCH_DISCOUNT
    return round(dollars * 1_000_000)


def calls_today() -> int:
    """지난 24시간 동안 실제로 API 를 부른 횟수. 국내·미국을 합쳐 센다.

    `input_tokens > 0` 인 행만 센다. 0 이면 API 를 부르기 전에 실패한 것이라
    돈이 들지 않았다.
    """
    since = datetime.now(timezone.utc) - timedelta(days=1)
    total = 0
    with get_session() as session:
        for model in (SecAnalysis, DartAnalysis):
            total += session.execute(
                select(func.count())
                .select_from(model)
                .where(model.created_at >= since, model.input_tokens > 0)
            ).scalar_one()
    return total


def total_cost_micro_usd() -> int:
    """누적 추정 비용. 국내·미국 합계."""
    total = 0
    with get_session() as session:
        for model in (SecAnalysis, DartAnalysis):
            total += session.execute(
                select(func.coalesce(func.sum(model.cost_micro_usd), 0))
            ).scalar_one()
    return total


def total_analyses() -> int:
    total = 0
    with get_session() as session:
        for model in (SecAnalysis, DartAnalysis):
            total += session.execute(select(func.count()).select_from(model)).scalar_one()
    return total


def check_daily_limit() -> None:
    """상한을 넘었으면 예외. 실제 호출 직전에 부른다."""
    limit = get_settings().analysis_daily_limit
    used = calls_today()
    if used >= limit:
        raise BudgetExceeded(
            f"하루 분석 상한({limit}건)에 도달했습니다. 지난 24시간 동안 {used}건을 "
            "분석했습니다(국내·미국 합산).\n"
            "비용 사고를 막기 위한 제한입니다. 내일 다시 시도하거나 .env 의 "
            "ANALYSIS_DAILY_LIMIT 을 올려 주세요."
        )
