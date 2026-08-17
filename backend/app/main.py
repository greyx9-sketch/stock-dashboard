"""FastAPI 진입점.

지금 붙어 있는 것: 헬스체크, 국내 주식 조회(KRX 확정 종가), 데이터 현황.
미국 주식·공시·재무·기업분석은 단계별로 붙여 나간다.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import PROJECT_ROOT, get_settings
from app.models.base import init_db
from app.routers import (
    disclosures,
    financials,
    kr_analysis,
    meta,
    prices,
    stocks,
    us_analysis,
    us_stocks,
)
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
    # 10-K 분석 실행만 POST 다. 나머지는 전부 읽기다.
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# 국내 분석 라우터를 stocks 보다 먼저 등록한다. stocks 의 `/{symbol}` 포괄 경로가
# 먼저 잡으면 `/analysis` 가 종목 코드로 오인된다(미국 쪽과 같은 이유).
app.include_router(kr_analysis.router)
app.include_router(stocks.router)
app.include_router(prices.router)
app.include_router(disclosures.router)
app.include_router(disclosures.meta_router)
app.include_router(financials.router)
# 분석 라우터를 us_stocks 보다 먼저 등록한다. us_stocks 의 `/{ticker}` 포괄 경로가
# `/analysis/...` 를 티커로 오인해 먼저 잡는 것을 막는다.
app.include_router(us_analysis.router)
app.include_router(us_stocks.router)
app.include_router(meta.router)


@app.get("/health", tags=["시스템"])
def health() -> dict[str, str]:
    """서버가 살아 있는지 확인한다.

    배포 후 상시 구동 여부를 감시하는 데 쓴다.
    """
    return {"status": "ok"}


# ---------------------------------------------------------------- 화면 서빙
#
# 배포하면 이 서버가 화면(빌드된 프론트엔드)까지 함께 내보낸다. 프로세스를 하나만 띄우면
# 되므로 서버 관리가 단순해지고, 화면과 API 가 같은 주소에서 나오니 CORS 도 필요 없어진다.
#
# 개발 중에는 이 폴더가 없다(Vite 개발 서버가 5173 에서 따로 뜬다). 없으면 조용히 건너뛴다.
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def _mount_frontend(app: FastAPI) -> None:
    index_file = FRONTEND_DIST / "index.html"
    if not index_file.exists():
        return

    # 해시가 붙은 자산은 내용이 바뀌면 파일명도 바뀐다. 길게 캐시해도 안전하다.
    app.mount(
        "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets"
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        """화면 파일을 내보낸다.

        API 경로는 위에서 이미 처리됐으므로 여기까지 오면 화면 요청이다. 다만 없는 API 를
        부른 요청이 여기 흘러와 index.html 을 200 으로 받으면 오류를 알아채기 어렵다.
        그래서 /api 로 시작하는 것은 404 로 돌려보낸다.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="없는 API 경로입니다.")

        candidate = (FRONTEND_DIST / full_path).resolve()
        # 경로에 .. 를 섞어 폴더 밖 파일을 요구하는 것을 막는다.
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(FRONTEND_DIST.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(index_file)


@app.get("/api", tags=["시스템"], include_in_schema=False)
def api_root() -> dict[str, str]:
    """API 가 살아 있는지와 문서 위치를 알려준다."""
    settings = get_settings()
    return {
        "service": "증권 정보 대시보드",
        "env": settings.app_env,
        "docs": "/docs",
    }


# 화면 서빙은 반드시 모든 API 라우터를 등록한 뒤에 붙인다. 순서가 뒤바뀌면
# 포괄 경로(/{full_path})가 API 요청까지 먼저 잡아 버린다.
_mount_frontend(app)
