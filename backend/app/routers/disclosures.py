"""공시 조회 엔드포인트.

OpenDART 를 그때그때 호출한다. 공시는 새로 올라오는 즉시 보이는 편이 낫고, 종목 하나당
호출 1건이면 끝나서 굳이 미리 받아 둘 이유가 없다.

다만 같은 종목을 반복해서 열면 그만큼 호출이 나간다. 일일 한도가 20,000 건이므로
짧은 캐시를 둬서 연달아 보는 동안에는 다시 부르지 않게 했다.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.clients.dart import REPORT_TYPES, DartClient, DartError, Disclosure
from app.services import dart_corps

router = APIRouter(prefix="/api/stocks", tags=["공시"])

# 같은 종목을 다시 열었을 때 재호출하지 않는 시간(초).
CACHE_TTL_SEC = 300.0

# 기본 조회 기간(일). 최근 흐름을 보는 데 1년이면 충분하고, 더 필요하면 days 로 넓힌다.
DEFAULT_DAYS = 365

_cache: dict[tuple[str, int, bool, str | None], tuple[float, list[Disclosure]]] = {}


class DisclosureOut(BaseModel):
    """공시 한 건."""

    receipt_no: str = Field(description="접수번호")
    report_name: str = Field(description="보고서명")
    filer_name: str = Field(description="제출인")
    received_date: str = Field(description="접수일 (YYYY-MM-DD)")
    remark: str = Field(description="비고. 정정·첨부 여부 등이 표시된다")
    viewer_url: str = Field(description="DART 원문 보기 주소")


class DisclosuresOut(BaseModel):
    stock_code: str
    corp_name: str
    corp_code: str = Field(description="DART 고유번호")
    period_days: int = Field(description="조회한 기간(일)")
    report_type: str | None = Field(description="적용한 공시 유형 코드")
    report_type_label: str | None = Field(description="공시 유형 이름")
    disclosures: list[DisclosureOut]


@router.get("/disclosure-types", summary="공시 유형 목록")
def list_report_types() -> dict[str, str]:
    """화면의 필터 버튼을 만들 때 쓴다. 코드 → 이름."""
    return REPORT_TYPES


@router.get("/{symbol}/disclosures", summary="종목 공시 목록")
async def get_disclosures(
    symbol: str = Path(description="단축코드 6자리 (예: 005930)", pattern=r"^\d{6}$"),
    days: int = Query(DEFAULT_DAYS, ge=1, le=3650, description="최근 며칠간의 공시를 볼지"),
    count: int = Query(30, ge=1, le=100, description="가져올 건수"),
    final_only: bool = Query(
        True, description="최종보고서만 볼지. 켜면 나중에 정정된 원본이 빠져 읽기 쉽다"
    ),
    report_type: str | None = Query(
        None,
        description="공시 유형 코드 한 글자 (A 정기공시, B 주요사항보고 …). 비우면 전체",
        pattern=r"^[A-J]$",
    ),
) -> DisclosuresOut:
    """이 종목의 공시를 최신순으로 돌려준다."""
    corp = dart_corps.get_corp(symbol)
    if corp is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{symbol}' 의 DART 고유번호를 찾지 못했습니다.\n"
                "상장사 목록이 아직 받아지지 않았거나, 비상장·상장폐지 종목일 수 있습니다."
            ),
        )

    key = (symbol, days, final_only, report_type)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_TTL_SEC:
        rows = cached[1]
    else:
        end = date.today()
        begin = end - timedelta(days=days)
        try:
            async with DartClient() as dart:
                rows = await dart.get_disclosures(
                    corp.corp_code,
                    begin=begin,
                    end=end,
                    count=count,
                    final_only=final_only,
                    report_type=report_type,
                )
        except DartError as exc:
            # 인증키·한도 문제다. 사유를 그대로 화면에 보여줘야 사용자가 조치할 수 있다.
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except RuntimeError as exc:
            # config.require() — 키가 아직 없다.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        _cache[key] = (now, rows)

    return DisclosuresOut(
        stock_code=symbol,
        corp_name=corp.corp_name,
        corp_code=corp.corp_code,
        period_days=days,
        report_type=report_type,
        report_type_label=REPORT_TYPES.get(report_type) if report_type else None,
        disclosures=[
            DisclosureOut(
                receipt_no=d.receipt_no,
                report_name=d.report_name,
                filer_name=d.filer_name,
                received_date=d.received_date,
                remark=d.remark,
                viewer_url=d.viewer_url,
            )
            for d in rows[:count]
        ],
    )
