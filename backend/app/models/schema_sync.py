"""모델에 추가된 컬럼을 기존 DB 에 반영한다.

`Base.metadata.create_all()` 은 **없는 테이블만 만든다.** 이미 있는 테이블에 컬럼을
추가해도 아무 일도 하지 않으므로, 운영 중인 DB 는 모델과 어긋난 채로 남고 조회가
`no such column` 500 을 낸다. 그 간극을 메우는 것이 이 파일이다.

**왜 alembic 을 쓰지 않는가.**

1. 지금 필요한 변경이 `ADD COLUMN` 뿐이다. SQLite 에서 이것은 테이블을 재작성하지 않는
   O(1) 헤더 수정이라 위험도가 `CREATE TABLE` 수준이다. alembic 이 값어치를 내는 상황
   (컬럼 삭제·타입 변경)은 SQLite 에서 어차피 테이블 통째 재작성이고, 미리 깔아 둔다고
   그 위험이 줄지 않는다.
2. **배포에 빠뜨리기 쉬운 수동 단계가 생긴다.** `alembic upgrade head` 를 잊으면 서버는
   뜨는데 화면만 500 이 난다. 원인이 가장 안 보이는 종류의 고장이다. 이 프로젝트는
   비개발자가 운영하고, `CLAUDE.md` 는 사용자에게 코드 수정을 요구하지 않는다고 못 박는다.
3. 지금은 "모델 선언 = 스키마"가 유일한 진실이다. 리비전 파일이라는 두 번째 진실이
   생기면 둘을 맞추는 일이 새로 생긴다.
4. 되돌릴 수단은 이미 있다 — `backend/scripts/backup_db.py` 가 매일 검증된 사본을 만든다.

**이 헬퍼는 컬럼 추가만 한다.** 삭제·이름 변경·타입 변경은 하지 않고, 할 수 없다는 것을
로그로 알린다. 그런 변경이 처음 필요해지는 날이 alembic 도입을 다시 볼 시점이다.
"""

from __future__ import annotations

import logging

from sqlalchemy import Column, MetaData, Table, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateColumn

logger = logging.getLogger(__name__)


def _existing_columns(engine: Engine, table_name: str) -> set[str]:
    """DB 에 실제로 있는 컬럼 이름."""
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(f'PRAGMA table_info("{table_name}")').fetchall()
    # PRAGMA table_info 의 두 번째 필드가 컬럼 이름이다.
    return {row[1] for row in rows}


def _cannot_add(column: Column) -> str | None:
    """SQLite 가 `ADD COLUMN` 으로 붙일 수 없는 컬럼이면 그 이유를 돌려준다.

    마지막 조건이 이 헬퍼의 유일한 함정이다. SQLAlchemy 의 파이썬 레벨 `default=` 는
    DDL 에 나타나지 않으므로, `nullable=False` 인데 `server_default` 가 없으면
    SQLite 가 "기존 행을 무엇으로 채우란 말이냐"며 거절한다. 여기서 걸러내지 않으면
    서버 기동 때 터진다.
    """
    if column.primary_key:
        return "기본키는 나중에 추가할 수 없습니다"
    if column.unique:
        return "UNIQUE 컬럼은 나중에 추가할 수 없습니다"
    if not column.nullable and column.server_default is None:
        return "NOT NULL 이면서 server_default 가 없습니다 (기존 행을 채울 값이 없음)"
    return None


def missing_columns(engine: Engine, table: Table) -> list[Column]:
    """모델에는 있는데 DB 에는 없는 컬럼.

    테이블 자체가 없으면 빈 목록을 돌려준다 — 그건 `create_all` 이 할 일이다.
    """
    if not inspect(engine).has_table(table.name):
        return []
    have = _existing_columns(engine, table.name)
    return [c for c in table.columns if c.name not in have]


def add_missing_columns(engine: Engine, metadata: MetaData) -> list[str]:
    """부족한 컬럼을 채우고, 추가한 것들을 `["표.컬럼", ...]` 로 돌려준다.

    **`create_all()` 다음에 불러야 한다.** 없는 테이블은 건드리지 않기 때문이다.
    """
    added: list[str] = []

    for table in metadata.sorted_tables:
        for column in missing_columns(engine, table):
            reason = _cannot_add(column)
            if reason:
                # 멈추지 않고 알리기만 한다. 사람이 손으로 옮겨야 하는 변경이다.
                logger.warning(
                    "%s.%s 를 자동으로 추가하지 못했습니다 — %s", table.name, column.name, reason
                )
                continue

            # DDL 을 손으로 짜지 않는다. 타입 이름(BIGINT/VARCHAR(10)/DATETIME)을 직접
            # 매핑하다 틀리는 것을 막으려고 SQLAlchemy 에게 컴파일을 맡긴다.
            spec = CreateColumn(column).compile(dialect=engine.dialect)
            with engine.begin() as conn:
                conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN {spec}')
            added.append(f"{table.name}.{column.name}")

        # 모델에서 사라진 컬럼은 **지우지 않는다.** 지우는 순간 되돌릴 수 없고,
        # 남아 있어도 조회에 방해가 되지 않는다.
        if inspect(engine).has_table(table.name):
            orphans = _existing_columns(engine, table.name) - {c.name for c in table.columns}
            if orphans:
                logger.info(
                    "%s 에 모델에 없는 컬럼이 남아 있습니다(그대로 둡니다): %s",
                    table.name,
                    ", ".join(sorted(orphans)),
                )

    return added
