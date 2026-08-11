"""티커 → CIK 매핑 적재·조회.

약 1만 건이 한 번의 호출로 오고 자주 바뀌지 않으므로 DB 에 넣고 주기적으로만 갱신한다.
국내 DART 고유번호 매핑과 같은 방식이다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.clients.sec import SecClient
from app.models.base import get_session
from app.models.us_company import SecCompany

logger = logging.getLogger(__name__)

UPSERT_CHUNK = 500
STALE_AFTER_DAYS = 7


@dataclass(frozen=True)
class TickerSyncResult:
    rows: int
    skipped: bool


def get_company(ticker: str) -> SecCompany | None:
    with get_session() as session:
        return session.execute(
            select(SecCompany).where(SecCompany.ticker == ticker.strip().upper())
        ).scalar_one_or_none()


def company_count() -> int:
    with get_session() as session:
        return session.execute(select(func.count()).select_from(SecCompany)).scalar_one()


def last_synced_at() -> datetime | None:
    with get_session() as session:
        return session.execute(select(func.max(SecCompany.fetched_at))).scalar_one_or_none()


def is_stale() -> bool:
    synced = last_synced_at()
    if synced is None:
        return True
    # SQLite 는 시간대를 저장하지 않는다. 꺼내면 tzinfo 가 없으므로 UTC 로 본다.
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - synced > timedelta(days=STALE_AFTER_DAYS)


def search(keyword: str, limit: int = 20) -> list[SecCompany]:
    """티커나 회사명으로 찾는다."""
    text = keyword.strip()
    if not text:
        return []
    with get_session() as session:
        return list(
            session.execute(
                select(SecCompany)
                .where(
                    SecCompany.ticker.startswith(text.upper())
                    | SecCompany.name.icontains(text)
                )
                # 티커가 짧을수록 검색어와 가까운 회사일 가능성이 높다.
                .order_by(func.length(SecCompany.ticker), SecCompany.ticker)
                .limit(limit)
            ).scalars()
        )


def _save(companies: list) -> int:
    if not companies:
        return 0

    now = datetime.now(timezone.utc)
    # 같은 티커가 두 번 나오면 뒤엣것이 이긴다. 한 문장 안에 중복 키가 있으면 SQLite 가 막는다.
    unique: dict[str, dict] = {}
    for c in companies:
        unique[c.ticker] = {
            "ticker": c.ticker,
            "cik": c.cik,
            "name": c.name,
            "fetched_at": now,
        }
    rows = list(unique.values())
    updatable = [c for c in rows[0] if c != "ticker"]

    with get_session() as session:
        for start in range(0, len(rows), UPSERT_CHUNK):
            chunk = rows[start : start + UPSERT_CHUNK]
            stmt = sqlite_insert(SecCompany).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker"],
                set_={c: getattr(stmt.excluded, c) for c in updatable},
            )
            session.execute(stmt)
        session.commit()
    return len(rows)


async def sync_companies(*, force: bool = False) -> TickerSyncResult:
    """티커 매핑을 받아 저장한다. 최신이면 받지 않는다."""
    if not force and not is_stale():
        return TickerSyncResult(rows=company_count(), skipped=True)

    async with SecClient() as sec:
        companies = await sec.fetch_company_tickers()

    rows = await asyncio.to_thread(_save, companies)
    logger.info("SEC 티커 매핑 갱신: %d 건", rows)
    return TickerSyncResult(rows=rows, skipped=False)
