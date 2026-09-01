"""모델에 늘어난 컬럼을 기존 DB 에 붙이는 헬퍼 테스트.

**이 코드가 틀리면 운영 DB 가 다친다.** 그래서 확인할 것이 둘이다 —
① 컬럼이 실제로 생기는가 ② **기존 행의 값이 그대로 남는가.**
②가 더 중요하다. 이 프로젝트에서 다시 받아 올 수 없는 데이터(종목 메모)가 같은 DB 에 있다.

붙일 수 없는 컬럼(기본키·UNIQUE·기본값 없는 NOT NULL)을 만났을 때 **멈추지 않고 건너뛰는
것**도 함께 못 박는다. 서버 기동 중에 도는 코드라 예외를 던지면 사이트가 안 뜬다.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import BigInteger, Column, Integer, MetaData, String, Table, create_engine, text

from app.models.schema_sync import add_missing_columns, missing_columns


@pytest.fixture
def engine(tmp_path):
    """임시 파일 DB. 메모리 DB 는 연결마다 따로라 ALTER 확인에 쓸 수 없다."""
    return create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")


def _old_schema(engine) -> MetaData:
    """컬럼 두 개짜리 '예전' 테이블을 만들고 행을 넣어 둔다."""
    old = MetaData()
    Table(
        "financials",
        old,
        Column("id", Integer, primary_key=True),
        Column("revenue", BigInteger),
    )
    old.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO financials (id, revenue) VALUES (1, 1000), (2, 2000)"))
    return old


def _new_schema() -> MetaData:
    """컬럼이 늘어난 '지금' 모델."""
    new = MetaData()
    Table(
        "financials",
        new,
        Column("id", Integer, primary_key=True),
        Column("revenue", BigInteger),
        Column("capex", BigInteger),
        Column("currency", String(3)),
    )
    return new


# ---------------------------------------------------------------- 기본 동작


def test_missing_columns_lists_only_new_ones(engine):
    _old_schema(engine)
    names = [c.name for c in missing_columns(engine, _new_schema().tables["financials"])]
    assert names == ["capex", "currency"]


def test_columns_are_added(engine):
    _old_schema(engine)
    added = add_missing_columns(engine, _new_schema())
    assert added == ["financials.capex", "financials.currency"]

    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(financials)").fetchall()}
    assert {"capex", "currency"} <= cols


def test_existing_rows_survive(engine):
    """가장 중요한 확인. 기존 값이 사라지면 되돌릴 방법이 없다."""
    _old_schema(engine)
    add_missing_columns(engine, _new_schema())

    with engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT id, revenue, capex FROM financials ORDER BY id").fetchall()
    assert rows == [(1, 1000, None), (2, 2000, None)]


def test_running_twice_changes_nothing(engine):
    """서버는 뜰 때마다 이 함수를 부른다. 두 번째부터는 조용해야 한다."""
    _old_schema(engine)
    new = _new_schema()
    assert add_missing_columns(engine, new)
    assert add_missing_columns(engine, new) == []


def test_unknown_table_is_left_to_create_all(engine):
    """모델에만 있는 테이블은 여기서 만들지 않는다. `create_all` 의 몫이다."""
    other = MetaData()
    Table("brand_new", other, Column("id", Integer, primary_key=True))
    assert add_missing_columns(engine, other) == []


# ---------------------------------------------------------------- 붙일 수 없는 컬럼


def test_not_null_without_default_is_skipped_not_raised(engine):
    """SQLite 가 거절하는 조합이다. 기동 중에 예외를 던지면 사이트가 안 뜬다."""
    _old_schema(engine)
    bad = MetaData()
    Table(
        "financials",
        bad,
        Column("id", Integer, primary_key=True),
        Column("revenue", BigInteger),
        Column("must_have", Integer, nullable=False),
    )
    assert add_missing_columns(engine, bad) == []


def test_unique_column_is_skipped(engine):
    _old_schema(engine)
    bad = MetaData()
    Table(
        "financials",
        bad,
        Column("id", Integer, primary_key=True),
        Column("revenue", BigInteger),
        Column("ticker", String(10), unique=True),
    )
    assert add_missing_columns(engine, bad) == []


def test_not_null_with_server_default_is_added(engine):
    """`server_default` 가 있으면 기존 행을 채울 값이 있으므로 붙일 수 있다.

    `schema_version` 처럼 '이 행이 어느 판으로 저장됐는가'를 담는 컬럼이 이 형태다.
    """
    _old_schema(engine)
    ok = MetaData()
    Table(
        "financials",
        ok,
        Column("id", Integer, primary_key=True),
        Column("revenue", BigInteger),
        Column("schema_version", Integer, nullable=False, server_default=text("0")),
    )
    assert add_missing_columns(engine, ok) == ["financials.schema_version"]

    with engine.connect() as conn:
        versions = [r[0] for r in conn.exec_driver_sql("SELECT schema_version FROM financials").fetchall()]
    # 기존 행이 기본값으로 채워져야 한다.
    assert versions == [0, 0]


# ---------------------------------------------------------------- 지우지 않는다


def test_orphan_column_is_left_alone(engine):
    """모델에서 빠진 컬럼을 자동으로 지우면 되돌릴 수 없다. 그냥 둔다."""
    _old_schema(engine)
    shrunk = MetaData()
    Table("financials", shrunk, Column("id", Integer, primary_key=True))

    assert add_missing_columns(engine, shrunk) == []

    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(financials)").fetchall()}
    assert "revenue" in cols


def test_added_column_type_is_what_the_model_said(engine):
    """타입 이름을 손으로 매핑하지 않고 SQLAlchemy 에 맡기는 이유를 못 박는다."""
    _old_schema(engine)
    add_missing_columns(engine, _new_schema())

    with engine.connect() as conn:
        types = {
            row[1]: row[2]
            for row in conn.exec_driver_sql("PRAGMA table_info(financials)").fetchall()
        }
    assert types["capex"] == "BIGINT"
    assert types["currency"] == "VARCHAR(3)"


def test_sqlite_version_supports_add_column():
    """이 헬퍼가 기대는 기능이 실제로 있는지 확인한다(ADD COLUMN 은 3.2 부터)."""
    assert sqlite3.sqlite_version_info >= (3, 2)


# ---------------------------------------------------------------- 진짜 모델로 하는 확인
#
# 위 테스트들은 **헬퍼가 옳게 동작하는가**를 본다. 아래 하나는 다른 질문이다 —
# **우리가 선언한 컬럼이 그 헬퍼를 통과하는가.**
#
# 2026-09-01 에 그 차이로 배포가 깨졌다. `batch_id` 를 `server_default` 없이 선언했더니
# `add_missing_columns` 가 "NOT NULL 인데 채울 값이 없다"며 **경고만 남기고 건너뛰었고**,
# 그 뒤 분석 조회가 전부 500(`no such column`)이 됐다. 테스트는 매번 빈 DB 를 새로 만들어
# `create_all` 로 표를 통째로 만들었기 때문에 아무것도 잡지 못했다.
#
# 그래서 여기서는 **운영 DB 를 흉내 낸다** — 옛 표를 만들고, 행을 넣고, 새 모델로 맞춘다.


def test_analysis_tables_can_gain_new_columns(engine):
    """이미 행이 있는 분석 표에 새 컬럼이 실제로 붙는가.

    분석 표를 고를 이유가 있다 — 여기 담긴 것은 **돈을 주고 산 결과**라 다시 만들 수 없고,
    표를 새로 만드는 방식으로 도망칠 수도 없다.
    """
    from sqlalchemy import Column as SaColumn
    from sqlalchemy import MetaData as SaMetaData
    from sqlalchemy import Table as SaTable

    # 모델을 import 해야 테이블 정의가 Base 에 등록된다.
    from app.models import dart_analysis, us_analysis  # noqa: F401
    from app.models.base import Base

    for table_name in ("sec_analyses", "dart_analyses"):
        real = Base.metadata.tables[table_name]

        # `batch_id` 가 없던 시절의 표를 만든다.
        old = SaMetaData()
        SaTable(
            table_name,
            old,
            *[
                SaColumn(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable)
                for c in real.columns
                if c.name != "batch_id"
            ],
        )
        old.create_all(engine)

        added = add_missing_columns(engine, Base.metadata)

        have = {row[1] for row in sqlite3.connect(engine.url.database).execute(
            f'PRAGMA table_info("{table_name}")'
        )}
        assert "batch_id" in have, (
            f"{table_name}.batch_id 가 붙지 않았다. "
            "NOT NULL 컬럼을 새로 만들 때는 server_default 를 반드시 준다."
        )
        assert f"{table_name}.batch_id" in added

        # 붙기만 하고 못 읽으면 소용없다. 모든 컬럼을 실제로 조회해 본다.
        with engine.connect() as conn:
            conn.execute(real.select())
