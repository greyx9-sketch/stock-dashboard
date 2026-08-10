"""현재가 폴러.

토스증권 Open API 는 REST 만 제공하고 WebSocket 이 없다. 그래서 실시간처럼 보이게 하려면
서버가 주기적으로 현재가를 받아 두고, 브라우저는 그 값을 읽어 가는 구조로 만들어야 한다.

이 파일이 지키는 원칙 세 가지:

1. **브라우저가 토스를 직접 부르지 않는다.** 시크릿이 노출되고, 허용 IP 방식이라 애초에 막힌다.
   모든 외부 호출은 이 폴러 한 곳에서만 나간다.

2. **장이 닫혀 있으면 부르지 않는다.** 토스 장 운영시간 API 로 지금이 어느 세션인지 확인해
   정규장에는 촘촘히, 시간외에는 느슨하게, 휴장에는 아예 부르지 않는다. 공휴일표를 직접
   들고 있지 않아도 되고, 호출 한도를 낭비하지도 않는다.

3. **보고 있는 종목만 부른다.** 화면이 요청한 종목만 폴링 대상에 넣고, 한동안 아무도 찾지
   않으면 대상에서 뺀다. 2,872 종목을 5초마다 부르는 것은 불가능하고 필요하지도 않다.

응답은 항상 캐시에서 즉시 준다. 화면 요청이 외부 API 를 기다리는 일이 없어야
토스가 느려지거나 죽어도 화면은 계속 뜬다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from app.clients.toss import TossClient, TossError

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 한 번에 조회할 수 있는 종목 수. 토스 문서에 명시된 상한이다.
MAX_SYMBOLS_PER_CALL = 200

# 세션별 폴링 간격(초). 정규장에는 촘촘히, 시간외에는 느슨하게 본다.
INTERVAL_BY_PHASE: dict[str, float] = {
    "REGULAR": 5.0,
    "PRE": 15.0,
    "AFTER": 15.0,
    "CLOSED": 60.0,
    "HOLIDAY": 60.0,
    "UNKNOWN": 30.0,
}

# 아무도 찾지 않는 종목을 폴링 대상에서 빼기까지의 시간(초).
# 화면이 5초마다 요청하므로 이보다 짧으면 보고 있는 중에 빠져나간다.
SYMBOL_INTEREST_TTL = 120.0

# 장 운영시간을 다시 확인하는 주기(초). 하루에 몇 번 바뀌지도 않는 값이라 자주 볼 이유가 없다.
CALENDAR_REFRESH_SEC = 600.0

# 연속 실패 시 대기 시간의 상한(초). 토스가 죽었을 때 무한정 두드리지 않기 위한 것이다.
MAX_BACKOFF_SEC = 120.0

Phase = Literal["PRE", "REGULAR", "AFTER", "CLOSED", "HOLIDAY", "UNKNOWN"]

PHASE_LABEL: dict[str, str] = {
    "PRE": "프리마켓",
    "REGULAR": "정규장",
    "AFTER": "애프터마켓",
    "CLOSED": "장 마감",
    "HOLIDAY": "휴장일",
    "UNKNOWN": "확인 중",
}


@dataclass(frozen=True)
class CachedPrice:
    """폴러가 마지막으로 받아 둔 현재가."""

    symbol: str
    last_price: Decimal
    timestamp: str | None  # 토스가 알려준 체결 시각
    fetched_at: datetime  # 우리가 받아 온 시각

    def age_seconds(self, now: datetime | None = None) -> float:
        return ((now or datetime.now(timezone.utc)) - self.fetched_at).total_seconds()


@dataclass(frozen=True)
class MarketState:
    """지금 장이 어떤 상태인지. 화면 상단 표시와 폴링 주기 결정에 함께 쓴다."""

    phase: Phase
    label: str
    trade_date: str | None  # 오늘 날짜(영업일이면). 휴장이면 None
    next_open: str | None  # 다음 개장 시각 (ISO)
    session_end: str | None  # 현재 세션 종료 시각 (ISO)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def resolve_phase(calendar: dict[str, Any] | None, now: datetime) -> MarketState:
    """장 운영시간 응답과 현재 시각으로 지금 세션을 판단한다.

    응답의 `integrated` 는 KRX+NXT 통합 기준이라 프리마켓(08:00~09:00)과
    애프터마켓(15:30~20:00)까지 포함한다. 우리가 보여줄 현재가도 통합 기준이므로 맞다.
    """
    if not calendar:
        return MarketState("UNKNOWN", PHASE_LABEL["UNKNOWN"], None, None, None)

    today = calendar.get("today") or {}
    sessions = today.get("integrated")
    next_day = calendar.get("nextBusinessDay") or {}
    next_open = ((next_day.get("integrated") or {}).get("preMarket") or {}).get("startTime")

    if not sessions:
        # integrated 가 null 이면 휴장일이다. 공휴일표를 따로 볼 필요가 없다.
        return MarketState("HOLIDAY", PHASE_LABEL["HOLIDAY"], today.get("date"), next_open, None)

    for phase, key in (("PRE", "preMarket"), ("REGULAR", "regularMarket"), ("AFTER", "afterMarket")):
        window = sessions.get(key) or {}
        start = _parse(window.get("startTime"))
        end = _parse(window.get("endTime"))
        if start and end and start <= now < end:
            return MarketState(
                phase,  # type: ignore[arg-type]
                PHASE_LABEL[phase],
                today.get("date"),
                next_open,
                window.get("endTime"),
            )

    # 어느 세션에도 속하지 않는다. 개장 전이면 오늘 프리마켓이, 마감 후면 내일이 다음 개장이다.
    pre_start = (sessions.get("preMarket") or {}).get("startTime")
    upcoming = pre_start if (_parse(pre_start) and now < _parse(pre_start)) else next_open  # type: ignore[operator]
    return MarketState("CLOSED", PHASE_LABEL["CLOSED"], today.get("date"), upcoming, None)


class PricePoller:
    """현재가를 주기적으로 받아 캐시에 넣어 두는 백그라운드 작업.

    서버가 뜰 때 하나만 만들어 계속 돌린다. `register()` 로 관심 종목을 등록하고
    `snapshot()` 으로 캐시를 읽는다. 둘 다 외부 호출을 하지 않아 즉시 돌아온다.
    """

    def __init__(self) -> None:
        self._prices: dict[str, CachedPrice] = {}
        self._wanted: dict[str, float] = {}  # 종목 → 마지막으로 요청된 시각(monotonic)
        self._market = MarketState("UNKNOWN", PHASE_LABEL["UNKNOWN"], None, None, None)
        self._calendar_checked_at: float = 0.0
        self._last_error: str | None = None
        self._last_success_at: datetime | None = None
        self._failures = 0
        self._task: asyncio.Task[None] | None = None
        self._wakeup = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ 외부에서 쓰는 것

    def register(self, symbols: list[str]) -> None:
        """이 종목들을 보고 있다고 알린다. 폴링 대상에 들어간다.

        **다른 스레드에서 불린다.** 조회 엔드포인트는 동기 함수라 FastAPI 가 워커 스레드에서
        돌리기 때문이다. 그래서 시계는 이벤트 루프 시계가 아니라 `time.monotonic()` 을 쓰고,
        폴러를 깨울 때도 루프에 안전하게 넘긴다.
        """
        now = time.monotonic()
        fresh = [s for s in symbols if s not in self._wanted]
        for symbol in symbols:
            self._wanted[symbol] = now
        # 새로 들어온 종목이 있으면 다음 주기를 기다리지 않고 바로 한 번 받는다.
        if fresh:
            self._request_wakeup()

    def _request_wakeup(self) -> None:
        """폴링 루프를 즉시 깨운다. 어느 스레드에서 불려도 안전하게."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._wakeup.set)
        except RuntimeError:
            # 서버가 내려가는 중이면 루프가 이미 닫혀 있을 수 있다. 깨울 이유도 없다.
            pass

    def snapshot(self, symbols: list[str]) -> dict[str, CachedPrice]:
        """캐시에 있는 현재가를 돌려준다. 없는 종목은 빠진 채로 온다."""
        return {s: self._prices[s] for s in symbols if s in self._prices}

    @property
    def market(self) -> MarketState:
        return self._market

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_success_at(self) -> datetime | None:
        return self._last_success_at

    @property
    def watching(self) -> int:
        return len(self._wanted)

    # ------------------------------------------------------------------ 수명 관리

    async def start(self) -> None:
        if self._task is None or self._task.done():
            # 루프를 기억해 둔다. 워커 스레드에서 폴러를 깨울 때 필요하다.
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.create_task(self._run(), name="price-poller")

    async def stop(self) -> None:
        self._loop = None
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    # ------------------------------------------------------------------ 본체

    async def _run(self) -> None:
        """폴링 루프. 서버가 살아 있는 동안 계속 돈다."""
        while True:
            try:
                delay = await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # 루프는 어떤 예외로도 죽으면 안 된다.
                logger.exception("현재가 폴링 중 예상치 못한 오류")
                delay = INTERVAL_BY_PHASE["UNKNOWN"]

            # 새 종목이 등록되면 기다리는 도중이라도 즉시 깨어난다.
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            self._wakeup.clear()

    async def _tick(self) -> float:
        """한 주기. 다음까지 기다릴 시간(초)을 돌려준다."""
        self._drop_stale_interest()

        loop_now = time.monotonic()
        need_calendar = loop_now - self._calendar_checked_at > CALENDAR_REFRESH_SEC
        symbols = list(self._wanted)

        # 아무도 화면을 안 보고 있고 달력도 최신이면 부를 이유가 없다.
        if not symbols and not need_calendar:
            return INTERVAL_BY_PHASE[self._market.phase]

        try:
            async with TossClient() as toss:
                if need_calendar:
                    calendar = await toss.get_market_calendar_kr()
                    self._market = resolve_phase(calendar, datetime.now(KST))
                    self._calendar_checked_at = loop_now

                # 장이 열려 있으면 전부 갱신한다. 값이 계속 움직이기 때문이다.
                # 장 상태를 모를 때(UNKNOWN)도 일단 받는다. 화면이 비는 것보다 낫다.
                if self._market.phase in ("PRE", "REGULAR", "AFTER", "UNKNOWN"):
                    target = symbols
                else:
                    # 마감·휴장에는 값이 바뀌지 않으므로 갱신할 이유가 없다. 다만 아직 한 번도
                    # 받지 못한 종목은 채운다. 마감 후에도 마지막 체결가는 보여야 하기 때문이다.
                    target = [s for s in symbols if s not in self._prices]

                if target:
                    await self._fetch_prices(toss, target)

            self._failures = 0
            self._last_error = None
        except (TossError, RuntimeError) as exc:
            self._failures += 1
            self._last_error = str(exc)
            logger.warning("현재가 폴링 실패 (%d회 연속): %s", self._failures, exc)
            # 연속 실패하면 간격을 벌린다. 죽은 API 를 5초마다 두드려 봐야 소용없다.
            return min(MAX_BACKOFF_SEC, INTERVAL_BY_PHASE[self._market.phase] * 2**self._failures)

        return INTERVAL_BY_PHASE[self._market.phase]

    async def _fetch_prices(self, toss: TossClient, symbols: list[str]) -> None:
        """관심 종목의 현재가를 받아 캐시를 갱신한다. 200 개씩 끊어 부른다."""
        fetched_at = datetime.now(timezone.utc)
        for start in range(0, len(symbols), MAX_SYMBOLS_PER_CALL):
            chunk = symbols[start : start + MAX_SYMBOLS_PER_CALL]
            for row in await toss.get_prices(chunk):
                symbol = row.get("symbol")
                raw = row.get("lastPrice")
                if not symbol or raw is None:
                    continue
                self._prices[symbol] = CachedPrice(
                    symbol=symbol,
                    last_price=Decimal(str(raw)),
                    timestamp=row.get("timestamp"),
                    fetched_at=fetched_at,
                )
        self._last_success_at = fetched_at

    def _drop_stale_interest(self) -> None:
        """한동안 아무도 찾지 않은 종목을 폴링 대상에서 뺀다."""
        cutoff = time.monotonic() - SYMBOL_INTEREST_TTL
        for symbol in [s for s, seen in self._wanted.items() if seen < cutoff]:
            del self._wanted[symbol]
            self._prices.pop(symbol, None)


# 서버 전체가 공유하는 폴러 하나. 여러 개를 만들면 토스 토큰이 서로를 무효화한다.
poller = PricePoller()
