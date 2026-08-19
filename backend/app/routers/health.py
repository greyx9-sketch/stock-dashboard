"""가동 상태 엔드포인트.

`/health` 는 살아 있는지만 답한다(배포 스크립트와 오라클 경보가 쓴다).
여기 `/api/health/detail` 은 **무엇이 어떻게 고장났는지**까지 답한다.

두 곳이 같이 읽는다:
  - 화면 — 상태가 정상이 아니면 위쪽에 경고 띠를 띄운다.
  - `backend/scripts/watchdog.py` — 10분마다 읽고 문제가 있으면 알림을 보낸다.

같은 근거를 쓰므로 "메일은 왔는데 화면은 멀쩡" 같은 어긋남이 생기지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services import health as health_service

router = APIRouter(prefix="/api/health", tags=["시스템"])


class CheckOut(BaseModel):
    name: str
    status: str = Field(description="ok / degraded / down")
    detail: str


class ErrorOut(BaseModel):
    at: str
    path: str
    status: int
    detail: str


class HealthOut(BaseModel):
    status: str = Field(description="ok / degraded / down. 항목 중 가장 나쁜 것이 전체가 된다")
    summary: str = Field(description="알림 제목으로 쓸 한 줄")
    uptime_seconds: int = Field(description="서버가 뜬 지 얼마나 됐는가. 잦은 재시작을 본다")
    checks: list[CheckOut]
    recent_errors: list[ErrorOut] = Field(description="최근 5xx. 새 것부터 최대 10건")


@router.get("/detail", summary="가동 상태 상세")
def get_health_detail() -> HealthOut:
    """지금 앱이 정상인지 항목별로 답한다. 외부 API 를 부르지 않아 즉시 돌아온다.

    **HTTP 상태는 문제가 있어도 200 이다.** 이 응답 자체가 진단 결과이므로,
    500 으로 돌려주면 내용을 읽을 수 없게 된다.
    """
    result = health_service.assess()
    return HealthOut(
        status=result.status,
        summary=result.summary(),
        uptime_seconds=int(health_service.uptime_seconds()),
        checks=[CheckOut(**vars(c)) for c in result.checks],
        recent_errors=[
            ErrorOut(at=e.at.isoformat(), path=e.path, status=e.status, detail=e.detail)
            for e in result.recent_errors
        ],
    )
