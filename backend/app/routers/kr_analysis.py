"""사업보고서 서술 분석 엔드포인트 (국내).

미국 쪽 `us_analysis.py` 와 같은 규칙을 따른다:

- `GET`  은 저장된 것만 읽는다. **절대 API 를 부르지 않으므로 돈이 들지 않는다.**
- `POST` 만 분석을 실행한다.

읽기와 돈 쓰기를 메서드로 갈라 두면, 화면을 여는 것만으로 과금되는 사고가 구조적으로
막힌다. 화면은 상세를 열 때 GET 만 부르고, POST 는 사용자가 버튼을 눌러야 나간다.

사용량 조회는 미국 쪽 `/api/us/analysis/usage` 하나로 합쳐져 있다 — 지갑이 하나이므로
창구도 하나가 맞다.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.models.dart_analysis import STATUS_OK, DartAnalysis
from app.services import dart_analysis, dart_corps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stocks", tags=["국내 주식 — 사업보고서 분석"])


class RiskItemOut(BaseModel):
    title: str
    why_it_matters: str
    source: str = Field(description="보고서 어느 절에서 나온 내용인지")


class KrAnalysisOut(BaseModel):
    """분석 결과. `status` 로 세 가지 상태를 구분한다."""

    status: str = Field(description="ok=분석 있음 / none=아직 안 함 / failed=실패")
    stock_code: str

    corp_name: str | None = None
    report_name: str | None = None
    fiscal_year: int | None = None
    received_date: str | None = None
    source_url: str | None = None
    model: str | None = None
    generated_at: str | None = None
    sections: list[str] = Field(default_factory=list)
    truncated: list[str] = Field(default_factory=list)

    business_summary: str | None = None
    segments: list[str] = Field(default_factory=list)
    key_risks: list[RiskItemOut] = Field(default_factory=list)
    mdna_points: list[str] = Field(default_factory=list)
    moat_and_competition: str | None = None

    error: str | None = None


def _split(value: str) -> list[str]:
    return [part for part in value.split(",") if part]


def _to_out(stock_code: str, row: DartAnalysis | None) -> KrAnalysisOut:
    if row is None:
        return KrAnalysisOut(status="none", stock_code=stock_code)
    if row.status != STATUS_OK:
        return KrAnalysisOut(
            status="failed",
            stock_code=row.stock_code,
            corp_name=row.corp_name or None,
            error=row.error,
        )

    content = json.loads(row.content_json)
    return KrAnalysisOut(
        status="ok",
        stock_code=row.stock_code,
        corp_name=row.corp_name or None,
        report_name=row.report_name or None,
        fiscal_year=row.fiscal_year or None,
        received_date=row.received_date or None,
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


def _resolve(symbol: str):
    corp = dart_corps.get_corp(symbol)
    if corp is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{symbol}' 종목을 DART 매핑에서 찾지 못했습니다.\n"
                "상장 폐지되었거나 매핑이 아직 받아지지 않았을 수 있습니다."
            ),
        )
    return corp


SYMBOL_PATH = Path(description="종목 코드 6자리 (예: 005930)", pattern=r"^\d{6}$")


@router.get("/{symbol}/analysis", summary="저장된 사업보고서 분석 조회")
def get_analysis(symbol: str = SYMBOL_PATH) -> KrAnalysisOut:
    """저장된 분석을 돌려준다. **절대 새로 분석하지 않는다** — 돈이 들지 않는 경로다."""
    corp = _resolve(symbol)
    return _to_out(corp.stock_code, dart_analysis.load(corp.stock_code))


@router.post("/{symbol}/analysis", summary="사업보고서 분석 실행")
async def run_analysis(
    symbol: str = SYMBOL_PATH,
    force: bool = Query(
        False,
        description="돈을 쓰고 실패한 건을 다시 시도할지. 성공한 분석은 다시 부르지 않는다",
    ),
) -> KrAnalysisOut:
    """최신 사업보고서를 분석한다.

    이미 분석된 보고서면 그대로 돌려주고 API 를 부르지 않는다. 새로 분석하면 1~3분 걸린다
    — 원문이 수 MB 라 내려받는 데만 시간이 든다.
    """
    corp = _resolve(symbol)
    try:
        row = await dart_analysis.analyze(corp, force=force)
    except dart_analysis.AnalysisError as exc:
        # 하루 상한 초과가 대부분이다. 429 로 돌려 화면이 이유를 그대로 보여줄 수 있게 한다.
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RuntimeError as exc:
        # config.require() — ANTHROPIC_API_KEY 가 아직 없다.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _to_out(corp.stock_code, row)
