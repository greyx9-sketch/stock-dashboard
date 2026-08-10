"""FastAPI 진입점.

지금 붙어 있는 것: 헬스체크, 국내 주식 조회(KRX 확정 종가), 데이터 현황.
미국 주식·공시·재무·기업분석은 단계별로 붙여 나간다.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.models.base import init_db
from app.routers import meta, prices, stocks
from app.services.price_poller import poller
from app.services.scheduler import scheduler

# 개발 중 프론트엔드(Vite)가 뜨는 주소. 배포할 때는 같은 도메인에서 서비스하므로 필요 없어진다.
DEV_FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버가 뜨고 질 때 할 일.

    현재가 폴러는 서버가 사는 동안 계속 도는 백그라운드 작업이다. 여기서 하나만 띄운다.
    여러 개를 띄우면 토스 토큰이 서로를 무효화한다(토큰은 client 당 1개만 유효).

    스케줄러는 확정 종가를 매일 자동으로 받아 온다. 기동 직후에는 꺼져 있던 동안 빠진
    날짜를 따라잡는다.
    """
    init_db()
    await poller.start()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()
        await poller.stop()


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
app.include_router(prices.router)
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
