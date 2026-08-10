"""DART 고유번호 매핑 적재·조회.

종목코드 → 고유번호 매핑은 3.5MB ZIP 을 받아야 하는 무거운 호출이라 DB 에 넣어 두고 쓴다.
신규 상장이나 상호 변경이 있을 때만 바뀌므로 주 1회 갱신이면 충분하다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.clients.dart import DartClient
from app.models.base import get_session
from app.models.corp import DartCorp

logger = logging.getLogger(__name__)

UPSERT_CHUNK = 500

# 이보다 오래되면 다시 받는다. 신규 상장은 드물고, 며칠 늦게 반영돼도 문제가 되지 않는다.
STALE_AFTER_DAYS = 7


@dataclass(frozen=True)
class CorpSyncResult:
    rows: int
    skipped: bool  # 최신이라 받지 않았는가
    error: str | None = None


def get_corp_code(stock_code: str) -> str | None:
    """종목코드에 해당하는 DART 고유번호. 없으면 None."""
    with get_session() as session:
        return session.execute(
            select(DartCorp.corp_code).where(DartCorp.stock_code == stock_code)
        ).scalar_one_or_none()


def get_corp(stock_code: str) -> DartCorp | None:
    with get_session() as session:
        return session.execute(
            select(DartCorp).where(DartCorp.stock_code == stock_code)
        ).scalar_one_or_none()


def corp_count() -> int:
    with get_session() as session:
        return session.execute(select(func.count()).select_from(DartCorp)).scalar_one()


def last_synced_at() -> datetime | None:
    with get_session() as session:
        return session.execute(select(func.max(DartCorp.fetched_at))).scalar_one_or_none()


def is_stale() -> bool:
    """매핑을 다시 받아야 하는가."""
    synced = last_synced_at()
    if synced is None:
        return True
    # SQLite 는 시간대를 저장하지 않는다. 꺼내면 tzinfo 가 없으므로 UTC 로 간주한다.
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - synced > timedelta(days=STALE_AFTER_DAYS)


def _save(entries: list) -> int:
    """받아온 매핑을 DB 에 넣는다. 이미 있는 종목코드는 덮어쓴다."""
    if not entries:
        return 0

    now = datetime.now(timezone.utc)
    rows = [
        {
            "stock_code": e.stock_code,
            "corp_code": e.corp_code,
            "corp_name": e.corp_name,
            "modify_date": e.modify_date,
            "fetched_at": now,
        }
        for e in entries
    ]
    updatable = [c for c in rows[0] if c != "stock_code"]

    with get_session() as session:
        for start in range(0, len(rows), UPSERT_CHUNK):
            chunk = rows[start : start + UPSERT_CHUNK]
            stmt = sqlite_insert(DartCorp).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["stock_code"],
                set_={c: getattr(stmt.excluded, c) for c in updatable},
            )
            session.execute(stmt)
        session.commit()

    return len(rows)


async def sync_corp_codes(*, force: bool = False) -> CorpSyncResult:
    """고유번호 매핑을 받아 저장한다. 최신이면 받지 않는다."""
    if not force and not is_stale():
        return CorpSyncResult(rows=corp_count(), skipped=True)

    async with DartClient() as dart:
        entries = await dart.fetch_corp_codes()

    # 4천 행 upsert 는 동기 작업이다. 이벤트 루프를 붙잡지 않도록 스레드에서 돌린다.
    rows = await asyncio.to_thread(_save, entries)
    logger.info("DART 고유번호 매핑 갱신: 상장사 %d 건", rows)
    return CorpSyncResult(rows=rows, skipped=False)
