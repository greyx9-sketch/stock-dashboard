"""KRX 확정 종가 적재.

공공데이터포털에서 하루치 전 종목 시세를 받아 DB 에 넣는다.

이 API 는 실시간이 아니다. 어떤 날의 확정 종가는 **그다음 영업일 오후 1시 이후**에 올라온다.
그래서 "오늘 것을 지금 받는" 방식이 아니라, "아직 안 받은 날을 찾아 채우는" 방식으로 만들었다.
같은 날을 다시 받아도 덮어쓰기(upsert)라 중복이 생기지 않는다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.clients.krx import DailyQuote, KrxClient
from app.models.base import get_session, init_db
from app.models.quote import KrxDailyQuote

# 한 번의 INSERT 에 넣을 행 수. SQLite 는 한 문장의 파라미터 수에 상한이 있어서 끊어 넣는다.
UPSERT_CHUNK = 500

# 확정 종가가 공개되는 시각(한국시간 오후 1시). 이 전에는 어제 데이터를 조회해도 비어 있다.
PUBLISH_HOUR_KST = 13
KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class DayResult:
    """하루치 적재 결과."""

    day: date
    rows: int  # 저장한 종목 수. 0 이면 휴장일이거나 아직 공개 전이다.

    @property
    def is_empty(self) -> bool:
        return self.rows == 0


@dataclass(frozen=True)
class IngestResult:
    """여러 날 적재 결과 묶음."""

    days: list[DayResult]

    @property
    def total_rows(self) -> int:
        return sum(d.rows for d in self.days)

    @property
    def trading_days(self) -> list[DayResult]:
        return [d for d in self.days if not d.is_empty]

    @property
    def empty_days(self) -> list[DayResult]:
        return [d for d in self.days if d.is_empty]


def save_quotes(quotes: list[DailyQuote]) -> int:
    """받아온 시세를 DB 에 넣는다. 이미 있는 (거래일, 종목) 은 덮어쓴다.

    덮어쓰기로 만든 이유: 같은 날을 두 번 받아도 안전해야 재실행이 부담 없다.
    데이터가 나중에 정정되는 경우에도 다시 받으면 최신값으로 갱신된다.
    """
    if not quotes:
        return 0

    now = datetime.now(timezone.utc)
    rows = [
        {
            "trade_date": q.trade_date,
            "symbol": q.symbol,
            "isin": q.isin,
            "name": q.name,
            "market": q.market,
            "close": int(q.close),
            "change": int(q.change),
            "change_rate": q.change_rate,
            "open": int(q.open),
            "high": int(q.high),
            "low": int(q.low),
            "volume": int(q.volume),
            "trade_value": int(q.trade_value),
            "listed_shares": int(q.listed_shares),
            "market_cap": int(q.market_cap),
            "fetched_at": now,
        }
        for q in quotes
    ]

    # 기본키(거래일+종목코드)를 뺀 나머지를 갱신 대상으로 삼는다.
    updatable = [c for c in rows[0] if c not in ("trade_date", "symbol")]

    with get_session() as session:
        for start in range(0, len(rows), UPSERT_CHUNK):
            chunk = rows[start : start + UPSERT_CHUNK]
            stmt = sqlite_insert(KrxDailyQuote).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["trade_date", "symbol"],
                set_={c: getattr(stmt.excluded, c) for c in updatable},
            )
            session.execute(stmt)
        session.commit()

    return len(rows)


def stored_dates(begin: date, end: date) -> set[str]:
    """이미 저장된 거래일 목록. 같은 날을 다시 받지 않으려고 먼저 확인한다."""
    with get_session() as session:
        rows = session.execute(
            select(KrxDailyQuote.trade_date)
            .where(KrxDailyQuote.trade_date >= begin.isoformat())
            .where(KrxDailyQuote.trade_date <= end.isoformat())
            .group_by(KrxDailyQuote.trade_date)
        ).scalars()
        return set(rows)


def latest_available_date(now: datetime | None = None) -> date:
    """지금 시점에 데이터가 공개돼 있을 **가능성이 있는** 가장 최근 날짜.

    확정 종가는 다음 영업일 오후 1시 이후에 올라온다. 즉 오후 1시가 지나야 '어제'가
    후보가 되고, 그 전에는 '그저께'까지만 후보다. 휴장일 판단은 하지 않는다 —
    실제로 받아 보고 비어 있으면 휴장일로 취급하는 편이 공휴일표를 관리하는 것보다 정확하다.
    """
    now = now or datetime.now(KST)
    latest = now.date() - timedelta(days=1)
    if now.hour < PUBLISH_HOUR_KST:
        latest -= timedelta(days=1)
    return latest


async def ingest_days(days: list[date], *, skip_stored: bool = True) -> IngestResult:
    """주어진 날짜들의 전 종목 확정 시세를 받아 저장한다.

    `skip_stored=True` 면 이미 DB 에 있는 날은 호출조차 하지 않는다. 일일 한도가 10,000 건이고
    하루치가 3 건이므로 아껴 쓸 이유는 크지 않지만, 다시 돌렸을 때 빠른 편이 낫다.
    """
    init_db()

    targets = sorted(set(days), reverse=True)
    if skip_stored and targets:
        already = stored_dates(min(targets), max(targets))
        targets = [d for d in targets if d.isoformat() not in already]

    results: list[DayResult] = []
    async with KrxClient() as krx:
        for day in targets:
            quotes = await krx.get_quotes_for_date(day)
            # 2,900 행 upsert 는 동기 작업이라 그대로 실행하면 그동안 이벤트 루프가 멈춘다.
            # 스케줄러가 이걸 돌리는 동안 현재가 폴러와 화면 응답이 같이 멎으면 안 된다.
            rows = await asyncio.to_thread(save_quotes, quotes)
            results.append(DayResult(day=day, rows=rows))

    return IngestResult(days=results)


async def ingest_recent(calendar_days: int = 10) -> IngestResult:
    """최근 며칠(달력 기준)을 훑어 아직 없는 날을 채운다.

    주말·공휴일이 섞여 있으므로 달력 일수로 받는다. 10 일이면 영업일 6~7 일이 들어온다.
    """
    end = latest_available_date()
    days = [end - timedelta(days=i) for i in range(calendar_days)]
    return await ingest_days(days)


def summarize() -> dict[str, object]:
    """DB 에 지금 무엇이 들어 있는지 한눈에 보여줄 값들."""
    with get_session() as session:
        total = session.execute(select(func.count()).select_from(KrxDailyQuote)).scalar_one()
        oldest = session.execute(select(func.min(KrxDailyQuote.trade_date))).scalar_one()
        newest = session.execute(select(func.max(KrxDailyQuote.trade_date))).scalar_one()
        day_count = session.execute(
            select(func.count(func.distinct(KrxDailyQuote.trade_date)))
        ).scalar_one()
    return {
        "총_행수": total,
        "거래일_수": day_count,
        "가장_오래된_날": oldest,
        "가장_최근_날": newest,
    }
