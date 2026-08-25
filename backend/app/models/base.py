"""DB 연결과 테이블 정의의 뿌리.

SQLite 파일 하나에 전부 담는다. 이 프로젝트는 읽기 전용 대시보드이고 동시 사용자가
몇 명 되지 않으므로 별도 DB 서버를 둘 이유가 없다.

동기(sync) SQLAlchemy 를 쓴다. 외부 API 호출은 비동기로 하되, 로컬 SQLite 쓰기는
밀리초 단위라 비동기로 만들 실익이 없고 코드만 복잡해진다. FastAPI 는 `async` 가 아닌
경로 함수를 자동으로 별도 스레드에서 돌리므로 서버가 멈추지도 않는다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import PROJECT_ROOT, get_settings
from app.models.schema_sync import add_missing_columns


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """모든 테이블 정의가 상속하는 부모 클래스."""


def _resolve_database_url() -> str:
    """.env 의 DATABASE_URL 을 실제로 열 수 있는 경로로 바꾼다.

    `sqlite:///./data/app.db` 는 '현재 작업 디렉터리 기준' 이라, 스크립트를 어느 폴더에서
    실행하느냐에 따라 DB 파일이 여기저기 생긴다. 프로젝트 루트 기준 절대경로로 고정한다.
    """
    url = get_settings().database_url
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url

    raw_path = url[len(prefix) :]
    path = Path(raw_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / raw_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path}"


DATABASE_URL = _resolve_database_url()

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    """SQLite 기본값 중 이 프로젝트에 불리한 두 가지를 켠다.

    - WAL: 배치로 종가를 적재하는 중에도 화면 조회가 막히지 않게 한다.
    - foreign_keys: SQLite 는 외래키 제약을 기본으로 끄고 있다. 켜 두어야 실수를 잡는다.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_session() -> Session:
    """세션 하나를 연다. `with get_session() as session:` 형태로 쓴다."""
    return SessionLocal()


def init_db() -> None:
    """없는 테이블을 만들고, 모델에 새로 생긴 컬럼을 기존 테이블에 붙인다.

    **서버가 뜰 때 폴러·스케줄러보다 먼저 불려야 한다**(`app/main.py` 참고).
    컬럼 추가는 SQLite 에서 배타 락을 잡으므로, 백그라운드 작업이 DB 를 쓰기 시작하기
    전에 끝나야 안전하다. 이 순서를 바꾸지 말 것.

    컬럼 **삭제·타입 변경**은 여전히 처리하지 못한다. 그때가 오면 마이그레이션 도구를
    붙인다 — 판단 근거는 `app/models/schema_sync.py` 첫머리에 적어 두었다.
    """
    # import 해야 테이블 정의가 Base 에 등록된다. 순환 import 를 피해 함수 안에서 부른다.
    from app.models import (  # noqa: F401
        corp,
        dart_analysis,
        dividend,
        event,
        financial,
        macro,
        note,
        quarterly,
        quote,
        us_analysis,
        us_company,
        us_quarterly,
        watchlist,
    )

    Base.metadata.create_all(engine)

    # create_all 은 **없는 테이블만** 만든다. 이미 있는 테이블에 컬럼이 늘어난 경우는
    # 여기서 따로 붙인다. 반드시 create_all 다음이어야 한다.
    added = add_missing_columns(engine, Base.metadata)
    if added:
        logger.info("컬럼 추가: %s", ", ".join(added))
