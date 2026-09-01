"""10-K 서술 분석 엔드포인트.

`us_stocks.py` 에 넣지 않고 파일을 나눴다. 저기는 이미 350줄이고, 무엇보다 **이 프로젝트에서
유일하게 돈이 나가는 경로**라 따로 두는 편이 감시하기 쉽다.

- `GET  /api/us/{ticker}/analysis`  저장된 결과를 돌려준다. 절대 API 를 부르지 않는다.
- `POST /api/us/{ticker}/analysis`  없으면 분석한다. 30초~2분 걸린다.
- `GET  /api/us/analysis/usage`     오늘 몇 건 썼고 누적 추정 비용이 얼마인지.

읽기(GET)와 돈 쓰기(POST)를 메서드로 갈라 둔 이유는, 화면을 여는 것만으로 과금이 일어나는
사고를 구조적으로 막기 위해서다. 화면은 GET 만 부르고, POST 는 사용자가 버튼을 눌러야 나간다.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.clients.sec import SecError
from app.models.us_analysis import STATUS_OK, STATUS_PENDING, SecAnalysis
from app.services import llm_budget, sec_companies, tenk_analysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/us", tags=["미국 주식 — 10-K 분석"])


class RiskItemOut(BaseModel):
    title: str
    why_it_matters: str
    is_boilerplate: bool = Field(
        description="모든 보고서에 붙는 형식적 위험이면 true"
    )


class UsAnalysisOut(BaseModel):
    """분석 결과. `status` 로 세 가지 상태를 구분한다."""

    status: str = Field(
        description="ok=분석 있음 / none=아직 안 함 / pending=맡겨 둔 중 / failed=실패"
    )
    ticker: str

    # status 가 ok 일 때만 채워진다.
    fiscal_year: int | None = None
    period_end: str | None = None
    filed_date: str | None = None
    source_url: str | None = None
    model: str | None = None
    generated_at: str | None = None
    sections: list[str] = Field(default_factory=list, description="분석에 넣은 항목")
    truncated: list[str] = Field(
        default_factory=list, description="길이 상한에 걸려 앞부분만 넣은 항목"
    )

    business_summary: str | None = None
    segments: list[str] = Field(default_factory=list)
    key_risks: list[RiskItemOut] = Field(default_factory=list)
    mdna_points: list[str] = Field(default_factory=list)
    moat_and_competition: str | None = None

    # status 가 failed 일 때만 채워진다.
    error: str | None = None


class AnalysisUsageOut(BaseModel):
    calls_last_24h: int
    daily_limit: int
    total_analyses: int
    total_cost_usd: float = Field(description="누적 추정 비용. 정가 기준이라 실제보다 크다")
    model: str
    prompt_version: int


def _split(value: str) -> list[str]:
    return [part for part in value.split(",") if part]


def _to_out(ticker: str, row: SecAnalysis | None) -> UsAnalysisOut:
    if row is None:
        return UsAnalysisOut(status="none", ticker=ticker)
    # 배치에 맡겨 놓고 기다리는 중. **실패와 같은 칸에 묶지 않는다** — 사용자가
    # 다시 누를 일이 아니고, 곷 나온다고 말해 줘야 한다.
    if row.status == STATUS_PENDING:
        return UsAnalysisOut(status="pending", ticker=row.ticker)
    if row.status != STATUS_OK:
        return UsAnalysisOut(status="failed", ticker=row.ticker, error=row.error)

    content = json.loads(row.content_json)
    return UsAnalysisOut(
        status="ok",
        ticker=row.ticker,
        fiscal_year=row.fiscal_year,
        period_end=row.period_end or None,
        filed_date=row.filed_date or None,
        source_url=row.source_url or None,
        model=row.model,
        generated_at=row.created_at.isoformat() if row.created_at else None,
        sections=_split(row.sections),
        truncated=_split(row.truncated),
        business_summary=content.get("business_summary"),
        segments=content.get("segments", []),
        key_risks=[RiskItemOut(**r) for r in content.get("key_risks", [])],
        mdna_points=content.get("mdna_points", []),
        moat_and_competition=content.get("moat_and_competition"),
    )


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


TICKER_PATH = Path(description="티커 (예: AAPL)", pattern=r"^[A-Za-z0-9.\-]{1,12}$")


@router.get("/analysis/usage", summary="분석 사용량·비용 (국내·미국 합산)")
def get_usage() -> AnalysisUsageOut:
    """지금까지 몇 건을 분석했고 얼마를 썼는지. 비용 사고를 눈으로 확인하는 창구다.

    국내 사업보고서 분석과 **합산**이다. 하루 상한도 합산으로 걸린다 — 상한은 지갑
    기준이지 시장 기준이 아니다.
    """
    from app.config import get_settings

    return AnalysisUsageOut(
        calls_last_24h=llm_budget.calls_today(),
        daily_limit=get_settings().analysis_daily_limit,
        total_analyses=llm_budget.total_analyses(),
        total_cost_usd=round(llm_budget.total_cost_micro_usd() / 1_000_000, 4),
        model=tenk_analysis.MODEL,
        prompt_version=tenk_analysis.PROMPT_VERSION,
    )


@router.get("/{ticker}/analysis", summary="저장된 10-K 분석 조회")
def get_analysis(ticker: str = TICKER_PATH) -> UsAnalysisOut:
    """저장된 분석을 돌려준다. **절대 새로 분석하지 않는다** — 돈이 들지 않는 경로다."""
    company = _resolve(ticker)
    return _to_out(company.ticker, tenk_analysis.load(company.ticker))


@router.post("/{ticker}/analysis", summary="10-K 분석 실행")
async def run_analysis(
    ticker: str = TICKER_PATH,
    force: bool = Query(
        False,
        description=(
            "돈을 쓰고 실패한 건을 다시 시도할지. 성공한 분석은 force 여도 다시 부르지 않는다"
        ),
    ),
) -> UsAnalysisOut:
    """최신 10-K 를 분석한다.

    이미 분석된 문서면 그대로 돌려주고 API 를 부르지 않는다. 새로 분석하면 30초~2분 걸린다.
    """
    company = _resolve(ticker)
    try:
        row = await tenk_analysis.analyze(company, force=force)
    except tenk_analysis.AnalysisError as exc:
        # 하루 상한 초과가 대부분이다. 429 로 돌려 화면이 이유를 그대로 보여줄 수 있게 한다.
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except SecError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        # config.require() — ANTHROPIC_API_KEY 가 아직 없다.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _to_out(company.ticker, row)
