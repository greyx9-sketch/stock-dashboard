"""현재가 폴러.

서버가 현재가를 받아 두고 브라우저는 그 값을 읽어 간다. 값을 받는 길이 **둘**이다:

- **웹소켓**(`clients/toss_ws.py`) — 체결이 일어나는 그 순간 밀려 들어온다. 빠른 길.
- **REST 폴링**(이 파일) — 주기적으로 되묻는다. 첫 값·한도 초과분·유실을 메우는 안전망.

예전에는 토스에 웹소켓이 없어 폴링만이 길이었다. 2026-08-24 에 웹소켓이 생긴 것을
확인하고 얹었다. **폴링을 걷어내지 않은 이유는 `clients/toss_ws.py` 첫머리에 적었다** —
구독 직후엔 값이 안 오고, 구독은 100종목까지이며, 푸시는 유실될 수 있다.

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
from app.clients.toss_ws import TossTradeFeed

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 한 번에 조회할 수 있는 종목 수. 토스 문서에 명시된 상한이다.
MAX_SYMBOLS_PER_CALL = 200

# 세션별 폴링 간격(초). 정규장에는 촘촘히, 시간외에는 느슨하게 본다.
INTERVAL_BY_PHASE: dict[str, float] = {
    # 1초로 잡은 근거 (2026-08-24 실측·원문 확인):
    #
    #   - 토스가 실제로 그보다 자주 값을 바꾼다. **프리마켓인데도** NVDA 는 30초 동안
    #     11번(평균 2.7초에 한 번), TSLA 는 5번 바뀌었다. 정규장이면 더 잦다.
    #     5초로 두면 그 사이 움직임이 통째로 안 보인다.
    #   - 한도에 여유가 있다. 현재가는 MARKET_DATA 그룹이고 문서상 **초당 15회**인데,
    #     한 번 호출이 200 종목을 덮으므로 시장 둘을 동시에 봐도 초당 2회다.
    #   - 하루 총량 제한은 없다. 초당 제한(TPS)만 있다.
    #
    # 한 번 오가는 데 0.3~1초가 걸리므로 실제 주기는 1.3~1.5초에 가깝다. 그보다 더
    # 줄이려면 폴링이 아니라 웹소켓으로 가야 한다(토스가 그 사이 웹소켓을 추가했다).
    "REGULAR": 1.0,
    "DAY": 1.0,  # 미국 종목의 토스 데이마켓. 정규장처럼 실제 체결이 일어난다.
    "PRE": 15.0,
    "AFTER": 15.0,
    "CLOSED": 60.0,
    "HOLIDAY": 60.0,
    "UNKNOWN": 30.0,
}

# 웹소켓이 그 종목들을 전부 덮고 있을 때의 REST 주기(초).
#
# **웹소켓이 붙어 있어도 REST 를 끄지 않는다.** 시세 푸시는 LOSSY 이고 유실을 감지할
# sequence 도 없어서, 연결이 살아 있는 채로 조용해져도 우리가 알 방법이 없다. 30초에
# 한 번 REST 로 맞춰 보면 그런 경우에도 화면이 30초 넘게 멈추지 않는다.
WS_SAFETY_INTERVAL_SEC = 30.0

# 값이 움직이는 시간대. 이 동안에만 현재가를 다시 받는다.
LIVE_PHASES = ("PRE", "REGULAR", "AFTER", "DAY")

# 아무도 찾지 않는 종목을 폴링 대상에서 빼기까지의 시간(초).
# 화면이 최대 30초 간격(다른 탭을 볼 때)으로 요청하므로 이보다 넉넉해야 보고 있는
# 중에 빠져나가지 않는다.
SYMBOL_INTEREST_TTL = 120.0

# 장 운영시간을 다시 확인하는 주기(초). 하루에 몇 번 바뀌지도 않는 값이라 자주 볼 이유가 없다.
CALENDAR_REFRESH_SEC = 600.0

# 연속 실패 시 대기 시간의 상한(초). 토스가 죽었을 때 무한정 두드리지 않기 위한 것이다.
MAX_BACKOFF_SEC = 120.0

Phase = Literal["PRE", "REGULAR", "AFTER", "DAY", "CLOSED", "HOLIDAY", "UNKNOWN"]

PHASE_LABEL: dict[str, str] = {
    "PRE": "프리마켓",
    "REGULAR": "정규장",
    "AFTER": "애프터마켓",
    "DAY": "데이마켓",
    "CLOSED": "장 마감",
    "HOLIDAY": "휴장일",
    "UNKNOWN": "확인 중",
}

# 국내와 미국은 응답 구조가 다르다.
# 국내는 KRX+NXT 통합 세션이 `integrated` 안에 들어 있고, 미국은 세션이 최상위에 있으면서
# 토스 자체 주간거래(dayMarket)가 하나 더 있다. 세션을 볼 순서도 다르다.
KR_SESSION_ORDER = (("PRE", "preMarket"), ("REGULAR", "regularMarket"), ("AFTER", "afterMarket"))
US_SESSION_ORDER = (
    ("DAY", "dayMarket"),
    ("PRE", "preMarket"),
    ("REGULAR", "regularMarket"),
    ("AFTER", "afterMarket"),
)


def classify_market(symbol: str) -> str:
    """종목 코드로 어느 시장인지 가른다. 국내는 숫자 6자리, 미국은 알파벳 티커다."""
    return "KR" if symbol.isdigit() and len(symbol) == 6 else "US"


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


@dataclass(frozen=True)
class _Window:
    """세션 하나. 어느 영업일에 속한 것인지도 함께 든다."""

    phase: str
    start: datetime
    end: datetime
    trade_date: str | None


def _windows(calendar: dict[str, Any], order, korea: bool) -> list[_Window]:
    """전일·당일·익일 세 영업일의 세션을 시간순 하나의 목록으로 펼친다.

    **세 날을 다 보는 것이 핵심이다.** 미국 정규장은 22:30 에 시작해 다음 날 05:00 에
    끝나고, 애프터마켓은 05:00~08:50 이다. 한국 시간으로 보면 **지금 진행 중인 세션이
    "어제" 영업일에 속해 있는 시간대가 매일 세 시간 넘게 생긴다.**

    당일만 보면 그 시간 동안 "장 마감"으로 판정되어 배지가 틀리게 뜨고, 폴러가 갱신을
    멈춰 현재가가 굳는다. 실제로 그렇게 동작하고 있었다.
    """
    result: list[_Window] = []
    for key in ("previousBusinessDay", "today", "nextBusinessDay"):
        day = calendar.get(key) or {}
        sessions = _sessions_of(day, order, korea)
        if not sessions:
            continue
        for phase, name in order:
            window = sessions.get(name) or {}
            begins = _parse(window.get("startTime"))
            ends = _parse(window.get("endTime"))
            if begins and ends:
                result.append(_Window(phase, begins, ends, day.get("date")))
    result.sort(key=lambda w: w.start)
    return result


def _sessions_of(day: dict[str, Any], order, korea: bool) -> dict[str, Any] | None:
    """그 날의 세션 묶음. 휴장이면 None."""
    if korea:
        # 국내는 한 겹 안에 들어 있다. 휴장일이면 그 값이 통째로 null 이다.
        return day.get("integrated")
    # 미국은 최상위에 있다. 세션이 하나도 없으면 휴장으로 본다.
    return day if any(day.get(name) for _, name in order) else None


def resolve_phase(
    calendar: dict[str, Any] | None, now: datetime, *, country: str = "KR"
) -> MarketState:
    """장 운영시간 응답과 현재 시각으로 지금 세션을 판단한다.

    국내: 세션이 `integrated`(KRX+NXT 통합) 안에 있고, 휴장일이면 그 값이 null 이다.
    미국: 세션이 최상위에 있고, 토스 데이마켓(09:00~17:00 KST)이 하나 더 있다.

    **당일만 보지 않는다.** 미국 세션은 한국 시간 자정을 넘어 이어지므로, 지금 열려 있는
    세션이 전 영업일에 속할 수 있다(`_windows` 주석 참고).
    """
    if not calendar:
        return MarketState("UNKNOWN", PHASE_LABEL["UNKNOWN"], None, None, None)

    korea = country == "KR"
    order = KR_SESSION_ORDER if korea else US_SESSION_ORDER

    today = calendar.get("today") or {}
    windows = _windows(calendar, order, korea)

    # 다음에 열리는 세션. 지금 열려 있든 아니든 화면에 필요하다.
    upcoming = next((w.start for w in windows if w.start > now), None)
    next_open = upcoming.isoformat() if upcoming else None

    for window in windows:
        if window.start <= now < window.end:
            return MarketState(
                window.phase,  # type: ignore[arg-type]
                PHASE_LABEL[window.phase],
                # 진행 중인 세션이 속한 영업일을 쓴다. 자정을 넘긴 미국 세션에서는
                # 달력의 "오늘"과 다르다.
                window.trade_date,
                next_open,
                window.end.isoformat(),
            )

    # 열려 있는 세션이 없다. 오늘 자체가 휴장인지, 아니면 장 사이 시간인지 가른다.
    if not _sessions_of(today, order, korea):
        return MarketState("HOLIDAY", PHASE_LABEL["HOLIDAY"], today.get("date"), next_open, None)
    return MarketState("CLOSED", PHASE_LABEL["CLOSED"], today.get("date"), next_open, None)


class PricePoller:
    """현재가를 주기적으로 받아 캐시에 넣어 두는 백그라운드 작업.

    서버가 뜰 때 하나만 만들어 계속 돌린다. `register()` 로 관심 종목을 등록하고
    `snapshot()` 으로 캐시를 읽는다. 둘 다 외부 호출을 하지 않아 즉시 돌아온다.
    """

    def __init__(self) -> None:
        self._prices: dict[str, CachedPrice] = {}
        self._wanted: dict[str, float] = {}  # 종목 → 마지막으로 요청된 시각(monotonic)
        # 국내와 미국은 장 시간이 완전히 다르다. 한쪽 상태를 다른 쪽에 쓰면 안 된다 —
        # 한국 애프터마켓(16시)에 미국 화면이 "애프터마켓"으로 뜨는 식이 된다.
        self._markets: dict[str, MarketState] = {
            "KR": MarketState("UNKNOWN", PHASE_LABEL["UNKNOWN"], None, None, None),
            "US": MarketState("UNKNOWN", PHASE_LABEL["UNKNOWN"], None, None, None),
        }
        self._calendar_checked_at: float = 0.0
        self._last_error: str | None = None
        self._last_success_at: datetime | None = None
        self._failures = 0
        self._task: asyncio.Task[None] | None = None
        self._wakeup = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        # 체결 푸시를 받는 웹소켓. 값은 여기(_prices)에 그대로 들어온다.
        self._feed = TossTradeFeed(self._on_trade)

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
    def markets(self) -> dict[str, MarketState]:
        return dict(self._markets)

    def market(self, country: str = "KR") -> MarketState:
        return self._markets.get(country, self._markets["KR"])

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_success_at(self) -> datetime | None:
        return self._last_success_at

    @property
    def watching(self) -> int:
        return len(self._wanted)

    def realtime_for(self, symbols: list[str]) -> bool:
        """**이 종목들이** 전부 웹소켓으로 들어오고 있는가.

        서버 전체가 아니라 묻는 쪽이 보고 있는 것만 따진다. 화면 하나가 50종목을
        보는데, 조금 전까지 다른 탭에서 보던 종목이 아직 목록에 남아 있다고(120초간
        남는다) "실시간이 아니다"라고 답하면 틀린 말이다 — 지금 이 화면의 종목은
        전부 실시간으로 들어오고 있기 때문이다.
        """
        return self._feed.covers(symbols)

    @property
    def realtime_detail(self) -> str:
        """사람이 읽을 실시간 연결 상태. 화면과 점검 메시지에 그대로 쓴다."""
        if not self._feed.connected:
            reason = self._feed.last_error
            return f"연결 끊김 — 폴링으로 받는 중{f' ({reason})' if reason else ''}"
        watching = set(self._wanted)
        covered = watching & self._feed.subscribed
        if watching and covered != watching:
            return f"일부만 실시간 ({len(covered)}/{len(watching)} 종목) — 나머지는 폴링"
        return "실시간"

    # ------------------------------------------------------------------ 수명 관리

    async def start(self) -> None:
        if self._task is None or self._task.done():
            # 루프를 기억해 둔다. 워커 스레드에서 폴러를 깨울 때 필요하다.
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.create_task(self._run(), name="price-poller")
        # 웹소켓은 붙지 않아도 사이트가 도는 곁다리다. 못 붙어도 폴링이 그대로 맡는다.
        await self._feed.start()

    async def stop(self) -> None:
        self._loop = None
        await self._feed.stop()
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

        # 종목을 시장별로 가른다. 국내와 미국은 장 시간이 달라 갱신 여부를 따로 판단해야 한다.
        by_market: dict[str, list[str]] = {"KR": [], "US": []}
        for symbol in self._wanted:
            by_market[classify_market(symbol)].append(symbol)

        # 웹소켓에도 같은 목록을 넘긴다. **최근에 요청된 순서로** 넘겨야 한도(100건)에
        # 걸려 잘릴 때 가장 오래 방치된 종목부터 빠진다.
        recent = sorted(self._wanted, key=lambda s: self._wanted[s], reverse=True)
        self._feed.set_symbols(
            [s for s in recent if classify_market(s) == "KR"],
            [s for s in recent if classify_market(s) == "US"],
        )

        # 아무도 화면을 안 보고 있고 달력도 최신이면 부를 이유가 없다.
        if not self._wanted and not need_calendar:
            return self._next_delay(by_market)

        try:
            async with TossClient() as toss:
                if need_calendar:
                    now = datetime.now(KST)
                    self._markets["KR"] = resolve_phase(
                        await toss.get_market_calendar_kr(), now, country="KR"
                    )
                    self._markets["US"] = resolve_phase(
                        await toss.get_market_calendar_us(), now, country="US"
                    )
                    self._calendar_checked_at = loop_now

                target: list[str] = []
                for country, symbols in by_market.items():
                    if not symbols:
                        continue
                    phase = self._markets[country].phase
                    # 장이 열려 있으면 전부 갱신한다. 값이 계속 움직이기 때문이다.
                    # 장 상태를 모를 때(UNKNOWN)도 일단 받는다. 화면이 비는 것보다 낫다.
                    if phase in LIVE_PHASES or phase == "UNKNOWN":
                        target.extend(symbols)
                    else:
                        # 마감·휴장에는 값이 바뀌지 않는다. 다만 아직 한 번도 받지 못한 종목은
                        # 채운다 — 마감 후에도 마지막 체결가는 보여야 하기 때문이다.
                        target.extend(s for s in symbols if s not in self._prices)

                if target:
                    await self._fetch_prices(toss, target)

            self._failures = 0
            self._last_error = None
        except (TossError, RuntimeError) as exc:
            self._failures += 1
            self._last_error = str(exc)
            logger.warning("현재가 폴링 실패 (%d회 연속): %s", self._failures, exc)
            # 연속 실패하면 간격을 벌린다. 죽은 API 를 5초마다 두드려 봐야 소용없다.
            base = self._next_delay(by_market)
            return min(MAX_BACKOFF_SEC, base * 2**self._failures)

        return self._next_delay(by_market)

    def _next_delay(self, by_market: dict[str, list[str]]) -> float:
        """다음 주기까지 기다릴 시간.

        보고 있는 종목이 속한 시장 중 **가장 빠른 주기**를 따른다. 국내와 미국을 동시에
        보고 있는데 한쪽만 장중이면 그쪽 속도에 맞춰야 그 화면이 멈춰 보이지 않는다.

        **웹소켓이 그 종목들을 전부 덮고 있으면 훨씬 느슨하게 본다.** 값은 이미 푸시로
        들어오고 있으므로 REST 는 유실을 메우는 안전망 역할만 하면 된다. 하나라도
        빠져 있으면(한도 초과·거부·연결 끊김) 원래 주기로 돌아간다 — 그 하나가 멈춰
        보이면 안 되기 때문이다.
        """
        intervals = [
            INTERVAL_BY_PHASE[self._markets[country].phase]
            for country, symbols in by_market.items()
            if symbols
        ]
        if not intervals:
            return INTERVAL_BY_PHASE["CLOSED"]

        base = min(intervals)
        live = [s for country, symbols in by_market.items() for s in symbols
                if self._markets[country].phase in LIVE_PHASES]
        if live and self._feed.covers(live):
            return max(base, WS_SAFETY_INTERVAL_SEC)
        return base

    async def _fetch_prices(self, toss: TossClient, symbols: list[str]) -> None:
        """관심 종목의 현재가를 받아 캐시를 갱신한다. 200 개씩 끊어 부른다.

        **종류주식은 표기가 갈린다.** SEC 는 하이픈으로(`BRK-A`), 토스는 점으로
        (`BRK.A`) 쓴다. 우리 티커는 SEC 를 따르므로 그대로 물으면 빈손으로 오고,
        없는 종목과 구별이 안 되어 "토스가 다루지 않는 종목"으로 보인다. 실제로
        버크셔의 현재가 칸이 영영 로딩 상태로 남았다.

        두 표기를 함께 물어보고 어느 쪽으로 답이 오든 우리 티커로 담는다 —
        토스가 하이픈 표기를 쓰는 종목이 있어도 잃지 않는다.
        """
        fetched_at = datetime.now(timezone.utc)
        # 물어볼 표기 → 우리 티커. `us_universe._toss_aliases` 와 같은 규칙이다.
        alias = {s: s for s in symbols}
        for symbol in symbols:
            if "-" in symbol:
                alias[symbol.replace("-", ".")] = symbol
        asked = sorted(alias)

        for start in range(0, len(asked), MAX_SYMBOLS_PER_CALL):
            chunk = asked[start : start + MAX_SYMBOLS_PER_CALL]
            for row in await toss.get_prices(chunk):
                symbol = alias.get(row.get("symbol"))
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

    def _on_trade(self, symbol: str, price: Decimal, timestamp: str | None) -> None:
        """웹소켓이 체결을 밀어줄 때마다 불린다. **이벤트 루프 안이라 가벼워야 한다.**

        아무도 안 보는 종목이면 버린다. 구독 해제가 한 박자 늦게 반영되는 사이에도
        프레임이 계속 오는데, 그걸 받아 두면 이미 지운 종목이 캐시에 되살아난다.
        """
        if symbol not in self._wanted:
            return

        now = datetime.now(timezone.utc)
        self._prices[symbol] = CachedPrice(
            symbol=symbol,
            last_price=price,
            timestamp=timestamp,
            fetched_at=now,
        )
        # 가동 점검이 이 값으로 "현재가가 살아 있는가"를 판단한다. 웹소켓으로 받은 것도
        # 갱신은 갱신이므로 함께 찍어 준다.
        self._last_success_at = now

    def _drop_stale_interest(self) -> None:
        """한동안 아무도 찾지 않은 종목을 폴링 대상에서 뺀다."""
        cutoff = time.monotonic() - SYMBOL_INTEREST_TTL
        for symbol in [s for s, seen in self._wanted.items() if seen < cutoff]:
            del self._wanted[symbol]
            self._prices.pop(symbol, None)


# 서버 전체가 공유하는 폴러 하나. 여러 개를 만들면 토스 토큰이 서로를 무효화한다.
poller = PricePoller()
