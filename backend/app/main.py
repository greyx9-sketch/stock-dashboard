"""FastAPI 진입점.

지금은 헬스체크 하나뿐이다. 시세·공시·분석 엔드포인트는 단계별로 붙여 나간다.
"""

from fastapi import FastAPI

from app.config import get_settings

app = FastAPI(
    title="증권 정보 대시보드",
    description="국내(KRX)·미국 주식의 시세·공시·재무·기업분석을 모아 보는 읽기 전용 대시보드",
    version="0.1.0",
)


@app.get("/health", tags=["시스템"])
def health() -> dict[str, str]:
    """서버가 살아 있는지 확인한다.

    배포 후 상시 구동 여부를 감시하는 데 쓴다.
    """
    return {"status": "ok"}


@app.get("/", tags=["시스템"])
def root() -> dict[str, str]:
    """지금 어느 단계인지 알려주는 임시 안내."""
    settings = get_settings()
    return {
        "service": "증권 정보 대시보드",
        "env": settings.app_env,
        "docs": "/docs",
    }
