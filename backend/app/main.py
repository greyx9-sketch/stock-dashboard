"""FastAPI 진입점.

지금 붙어 있는 것: 헬스체크, 국내 주식 조회(KRX 확정 종가), 데이터 현황.
미국 주식·공시·재무·기업분석은 단계별로 붙여 나간다.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.models.base import init_db
from app.routers import meta, stocks

# 개발 중 프론트엔드(Vite)가 뜨는 주소. 배포할 때는 같은 도메인에서 서비스하므로 필요 없어진다.
DEV_FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버가 뜰 때 DB 테이블이 있는지 확인한다. 없으면 만든다."""
    init_db()
    yield


app = FastAPI(
    title="증권 정보 대시보드",
    description="국내(KRX)·미국 주식의 시세·공시·재무·기업분석을 모아 보는 읽기 전용 대시보드",
    version="0.2.0",
    lifespan=lifespan,
)

# 프론트엔드는 다른 포트에서 뜨므로 브라우저가 기본적으로 호출을 막는다. 개발용 주소만 연다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_FRONTEND_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(stocks.router)
app.include_router(meta.router)


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
