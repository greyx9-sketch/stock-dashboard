"""메모 회고 — 그 메모를 쓴 뒤 주가가 어떻게 됐나.

메모는 기획서가 "이 프로젝트의 차별점" 이라 부른 기능이다. 지금까지 메모에 남는 것은
**언제 썼는지**뿐이었다. 여기에 그 뒤의 성적을 붙인다.

    2026-05-12 에 쓴 메모 · 그 뒤 +18.4% (코스피 +3.1%)

**돈도 LLM 도 쓰지 않는다.** 확정 종가는 이미 우리 DB 에 있고 지수는 토스가 준다.
순수 계산이라 절대 규칙 3(숫자는 LLM 에게 시키지 않는다)에도 걸리지 않는다.
시간이 갈수록 값어치가 커지는 종류의 기능이다 — 판단의 기록이 성적표가 된다.

## 어느 숫자를 쓰나

| 대상 | 출처 | 왜 |
| --- | --- | --- |
| 국내 종목 | KRX 확정 종가 (DB) | 관심종목·현재가 화면과 같은 숫자라야 한 화면에서 어긋나지 않는다 |
| 국내 지수 | 토스 지표 일봉 | 코스피·코스닥을 상장 시장에 맞춰 고른다 |
| 미국 종목 | 토스 일봉 (수정주가) | 미국에는 KRX 같은 확정 종가 소스가 없다 |
| 미국 지수 | 토스 `SPY` 일봉 | 토스 지표에 미국 지수가 없다. 매크로 띠도 같은 대역을 쓴다 |

**수정주가가 중요하다.** 액면분할한 날 하루에 -50% 가 찍히는 것은 주가가 내린 것이
아니다. 토스 일봉은 기본이 수정주가라 그대로 쓴다(`clients/toss.py:get_candle_page`).

## 조심한 것 셋

1. **휴장일에 쓴 메모.** 그 날짜의 종가가 없으므로 **직전 거래일** 종가를 쓴다.
   `Series.on_or_before` 하나가 주말·공휴일·상장 전을 한꺼번에 처리한다.
2. **거래가 멈춘 종목.** 상장폐지·거래정지면 마지막 종가가 한참 과거에 멈춰 있다.
   그 값으로 "+12%" 를 보여주면 지금도 그런 줄 안다. 아예 내보내지 않는다.
3. **기준가와 비교 대상의 짝.** 종목 수익률을 A→B 로 쟀으면 지수도 **같은 A→B** 로
   잰다. 지수만 오늘 값을 쓰면 국내 장중에 (확정 종가는 어제까지인데 지수는 오늘이라)
   하루치가 지수 쪽에만 더해진다.

메모를 쓴 날짜는 **한국 날짜로 센다.** 미국 종목도 마찬가지다 — 메모는 한국에서 쓰이고,
시리즈에서 그 날짜 이하의 마지막 거래일을 고르므로 최대 한 세션 차이다. 그래서 화면에
기준일을 함께 보여준다. 조용히 틀린 값을 보여주는 것보다 눈으로 알아채는 편이 낫다.
"""

from __future__ import annotations

import asyncio
import bisect
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select

from app.clients.toss import TossClient, TossError
from app.clock import KST, today_kst
from app.models.base import get_session
from app.models.quote import KrxDailyQuote
from app.services.notes import NoteOut
from app.services.price_poller import classify_market

logger = logging.getLogger(__name__)

# 캔들 한 페이지의 봉 수(토스 상한)와 이어 받을 페이지 수.
# 200 × 4 ≈ 3년치 거래일이다. 그보다 오래된 메모는 회고를 붙이지 않는다 — 호출 넷을
# 쓰고도 못 닿는 과거라면, 그 수익률은 이미 종목 차트를 보는 편이 빠르다.
PAGE_SIZE = 200
MAX_PAGES = 4

# 캔들 캐시 수명(초). 마지막 봉은 장중이면 계속 움직이므로 영구 캐시가 아니라 TTL 이다
# (절대 규칙 7 — 오늘 날짜가 든 값은 담아 두면 낡는다).
SERIES_TTL_SEC = 600.0

# 마지막 종가가 시장의 마지막 거래일보다 이만큼(달력일) 뒤처져 있으면 거래가 멈춘
# 종목으로 본다. 주말에 연휴가 붙어도 미국·국내 모두 나흘을 넘지 않으므로 열흘이면
# 정상 종목을 잘못 걸러낼 일이 없다.
STOPPED_AFTER_DAYS = 10

KR_INDEX_BY_MARKET = {"KOSPI": ("KOSPI", "코스피"), "KOSDAQ": ("KOSDAQ", "코스닥")}
US_INDEX = ("SPY", "S&P500")


@dataclass(frozen=True)
class Point:
    """거래일 하나의 종가."""

    date: str
    close: Decimal


@dataclass
class NoteReturn:
    """메모 한 건의 회고."""

    note_id: int
    symbol: str
    base_date: str  # 기준이 된 거래일 (메모를 쓴 날, 휴장이면 직전 거래일)
    base_close: Decimal
    as_of: str  # 비교 대상 거래일
    last_close: Decimal
    change_rate: float  # %
    days: int  # 두 거래일 사이의 달력 일수
    index_label: str | None  # 코스피 / 코스닥 / S&P500
    index_rate: float | None


class Series:
    """거래일 오름차순 종가 묶음. 없는 날짜를 물으면 직전 거래일로 답한다."""

    def __init__(self, points: list[Point]) -> None:
        # 페이지 경계에서 같은 봉이 겹쳐 오므로(`before` 가 inclusive) 거래일로 겹침을 걷는다.
        merged = {p.date: p for p in points}
        self._points = [merged[d] for d in sorted(merged)]
        self._dates = [p.date for p in self._points]

    def __len__(self) -> int:
        return len(self._points)

    def on_or_before(self, day: str) -> Point | None:
        """그 날의 종가. 휴장일이면 직전 거래일 종가다. 상장 전이면 없다."""
        idx = bisect.bisect_right(self._dates, day) - 1
        return self._points[idx] if idx >= 0 else None

    def latest(self) -> Point | None:
        return self._points[-1] if self._points else None

    def covers(self, day: str) -> bool:
        """그 날짜 이하의 봉을 하나라도 들고 있는가."""
        return bool(self._dates) and self._dates[0] <= day


def _num(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _point(candle: dict) -> Point | None:
    """캔들 하나를 (거래일, 종가) 로 줄인다.

    **오프셋을 믿지 않고 앞 10자만 쓴다.** 미국 종목의 오프셋이 실측에서 두 번 달랐다 —
    2026-08-18 에는 `2026-08-17T00:00:00-04:00`(현지), 2026-09-14 에는
    `2026-09-11T13:00:00.000+09:00`(한국시각)이었다. 어느 쪽이든 **날짜 부분은 그 세션의
    거래일**이라 앞 10자는 변하지 않는다. 오프셋으로 날짜를 다시 계산하면 그날 바뀐다.
    """
    day = (candle.get("timestamp") or "")[:10]
    close = _num(candle.get("closePrice"))
    if len(day) != 10 or close is None or close <= 0:
        return None
    return Point(day, close)


def _note_date(note: NoteOut) -> str:
    """메모를 쓴 날(한국 날짜). 저장은 UTC 라 KST 로 옮겨서 센다."""
    return datetime.fromisoformat(note.created_at).astimezone(KST).date().isoformat()


def _rate(before: Decimal, after: Decimal) -> float:
    return float((after / before - 1) * 100)


def _stopped(last_day: str, market_last: str) -> bool:
    """마지막 종가가 시장보다 한참 뒤처져 있는가 — 상장폐지·거래정지."""
    try:
        gap = date.fromisoformat(market_last) - date.fromisoformat(last_day)
    except ValueError:
        return False
    return gap > timedelta(days=STOPPED_AFTER_DAYS)


# ------------------------------------------------------------------ 국내: DB 확정 종가


def _kr_from_db(symbols: list[str]) -> tuple[dict[str, Series], dict[str, str], str | None]:
    """국내 종목의 확정 종가 묶음. 상장 시장과 시장 전체의 마지막 거래일도 같이 준다.

    종목 수가 몇 개이고 적재 기간도 한정돼 있어 한 번의 질의로 전부 읽어 온다.
    """
    if not symbols:
        return {}, {}, None

    stmt = select(
        KrxDailyQuote.symbol,
        KrxDailyQuote.trade_date,
        KrxDailyQuote.close,
        KrxDailyQuote.market,
    ).where(KrxDailyQuote.symbol.in_(symbols))

    points: dict[str, list[Point]] = {}
    markets: dict[str, str] = {}
    with get_session() as session:
        for symbol, trade_date, close, market in session.execute(stmt):
            points.setdefault(symbol, []).append(Point(trade_date, Decimal(close)))
            markets[symbol] = market
        market_last = session.execute(select(func.max(KrxDailyQuote.trade_date))).scalar()

    return {s: Series(p) for s, p in points.items()}, markets, market_last


# ------------------------------------------------------------------ 토스: 캔들 이어 받기

# 캔들 캐시. (종류, 심볼) → (받은 시각, 시리즈, 더 과거가 없는가)
_series_cache: dict[tuple[str, str], tuple[float, Series, bool]] = {}


async def _fetch_series(
    toss: TossClient, symbol: str, *, need: str, indicator: bool
) -> tuple[Series, bool]:
    """`need` 날짜에 닿을 때까지 캔들을 이어 받는다.

    다음 페이지 커서는 응답의 `nextBefore` 를 그대로 넘긴다 — 시각을 직접 계산하면
    타임존·거래일 경계에서 한 봉씩 어긋난다.
    """
    points: list[Point] = []
    before: str | None = None
    exhausted = False

    for _ in range(MAX_PAGES):
        if indicator:
            candles, next_before = await toss.get_indicator_candle_page(
                symbol, interval="1d", count=PAGE_SIZE, before=before
            )
        else:
            candles, next_before = await toss.get_candle_page(
                symbol, interval="1d", count=PAGE_SIZE, before=before
            )
        page = [p for p in (_point(c) for c in candles) if p is not None]
        points.extend(page)

        if not page or not next_before:
            exhausted = True
            break
        if min(p.date for p in page) <= need:
            break
        before = next_before

    return Series(points), exhausted


async def _series(
    toss: TossClient, symbol: str, *, need: str, indicator: bool = False
) -> Series | None:
    """캔들 시리즈. 같은 심볼을 여러 메모가 물어보므로 캐시한다."""
    key = ("idx" if indicator else "stk", symbol)
    cached = _series_cache.get(key)
    now = time.monotonic()
    if cached and (now - cached[0]) < SERIES_TTL_SEC:
        _, series, exhausted = cached
        # 캐시가 그 메모의 날짜까지 닿지 못하면 더 받아야 한다. 다만 이미 끝까지
        # 받아 둔 것이라면(`exhausted`) 다시 불러도 같은 답이라 부르지 않는다.
        if series.covers(need) or exhausted:
            return series if len(series) else None

    try:
        series, exhausted = await _fetch_series(toss, symbol, need=need, indicator=indicator)
    except TossError as exc:
        logger.warning("회고용 캔들 조회 실패 (%s): %s", symbol, exc)
        return None

    _series_cache[key] = (now, series, exhausted)
    return series if len(series) else None


# ------------------------------------------------------------------ 조립


def _pair(
    series: Series, note_day: str, market_last: str | None
) -> tuple[str, Decimal, str, Decimal] | None:
    """메모 날짜에 맞는 (기준일·기준가, 비교일·비교가) 를 고른다."""
    base = series.on_or_before(note_day)
    last = series.latest()
    if base is None or last is None:
        return None  # 메모를 쓴 시점에 아직 상장 전이었거나, 종가가 하나도 없다
    if _stopped(last.date, market_last or last.date):
        return None  # 거래가 멈춘 종목 — 낡은 종가로 수익률을 내보내지 않는다
    if last.date < base.date:
        return None
    return base.date, base.close, last.date, last.close


async def note_returns(notes: list[NoteOut]) -> tuple[list[NoteReturn], str | None]:
    """메모 목록에 회고를 붙인다. 붙이지 못한 메모는 결과에서 빠진다.

    실패해도 예외를 올리지 않는다. 회고는 메모 본문에 딸린 덧붙임이라, 지수 하나를
    못 받았다고 메모 화면이 통째로 비면 안 된다. 못 받은 이유는 `error` 로 돌려준다.
    """
    if not notes:
        return [], None

    days: dict[int, str] = {n.id: _note_date(n) for n in notes}
    kr = [n for n in notes if classify_market(n.symbol) == "KR"]

    kr_series, kr_markets, kr_market_last = _kr_from_db(sorted({n.symbol for n in kr}))

    # DB 가 메모 날짜까지 닿지 못하는 국내 종목 — 적재를 시작하기 전에 쓴 메모다.
    # 그런 종목은 기준가와 비교가를 **둘 다** 토스 일봉으로 받는다. 한쪽만 바꾸면
    # 출처가 다른 두 숫자를 빼는 꼴이 된다.
    kr_fallback = sorted(
        {
            n.symbol
            for n in kr
            if n.symbol not in kr_series or not kr_series[n.symbol].covers(days[n.id])
        }
    )

    def _index_for(note: NoteOut) -> tuple[str, str] | None:
        """이 메모를 견줄 지수. 국내는 상장 시장을 따라 코스피·코스닥이 갈린다.

        우리 KRX 표에 아예 없는 국내 종목이면 어느 시장인지 알 수 없다. 그때는 지수를
        붙이지 않는다 — 코스피로 찍어 맞히는 것보다 없는 편이 낫다.
        """
        if classify_market(note.symbol) != "KR":
            return US_INDEX
        return KR_INDEX_BY_MARKET.get(kr_markets.get(note.symbol, ""))

    # 어떤 심볼을 어디까지 받아야 하는가. 심볼 하나에 메모가 여럿 달리므로 **가장 오래된
    # 메모의 날짜**까지만 받으면 그 심볼의 모든 메모가 답을 얻는다.
    need_stock: dict[str, str] = {}
    need_index: dict[str, str] = {}
    for note in notes:
        day = days[note.id]
        if classify_market(note.symbol) != "KR" or note.symbol in kr_fallback:
            need_stock[note.symbol] = min(need_stock.get(note.symbol, day), day)
        pick = _index_for(note)
        if pick:
            need_index[pick[0]] = min(need_index.get(pick[0], day), day)

    toss_series: dict[str, Series] = {}
    index_series: dict[str, Series] = {}
    error: str | None = None

    if need_stock or need_index:
        # 무엇을 받는 중인지 결과와 짝지어 두고 한꺼번에 기다린다. 위치로만 맞추면
        # 나중에 순서를 한 줄 바꾸는 순간 값이 엉뚱한 종목에 붙는다.
        jobs: list[tuple[bool, str]] = [(False, s) for s in sorted(need_stock)]
        jobs += [(True, s) for s in sorted(need_index)]
        try:
            async with TossClient() as toss:
                fetched = await asyncio.gather(
                    *(
                        _series(
                            toss,
                            symbol,
                            need=(need_index if is_index else need_stock)[symbol],
                            indicator=is_index and symbol != US_INDEX[0],
                        )
                        for is_index, symbol in jobs
                    )
                )
        except TossError as exc:
            logger.warning("회고용 시세 조회 실패: %s", exc)
            fetched = []
            error = str(exc)
        except Exception:
            logger.exception("회고용 시세 조회 중 오류")
            fetched = []
            error = "시세를 받아 오지 못했습니다."

        for (is_index, symbol), series in zip(jobs, fetched):
            if series is None:
                continue
            (index_series if is_index else toss_series)[symbol] = series

    today = today_kst().isoformat()
    out: list[NoteReturn] = []

    for note in notes:
        note_day = days[note.id]
        is_kr = classify_market(note.symbol) == "KR"
        if is_kr and note.symbol not in kr_fallback:
            series, market_last = kr_series.get(note.symbol), kr_market_last
        else:
            series = toss_series.get(note.symbol)
            market_last = today  # 토스 일봉에는 시장 전체의 마지막 거래일이 없다
        if series is None:
            continue

        picked = _pair(series, note_day, market_last)
        if picked is None:
            continue
        base_date, base_close, as_of, last_close = picked

        index_label: str | None = None
        index_rate: float | None = None
        pick = _index_for(note)
        if pick and (idx := index_series.get(pick[0])) is not None:
            # 종목과 **같은 두 거래일**로 잰다. 지수만 오늘 값을 쓰면 하루치가 한쪽에만 더해진다.
            idx_base = idx.on_or_before(base_date)
            idx_last = idx.on_or_before(as_of)
            if idx_base and idx_last and idx_base.date <= idx_last.date:
                index_label = pick[1]
                index_rate = _rate(idx_base.close, idx_last.close)

        out.append(
            NoteReturn(
                note_id=note.id,
                symbol=note.symbol,
                base_date=base_date,
                base_close=base_close,
                as_of=as_of,
                last_close=last_close,
                change_rate=_rate(base_close, last_close),
                days=(date.fromisoformat(as_of) - date.fromisoformat(base_date)).days,
                index_label=index_label,
                index_rate=index_rate,
            )
        )

    return out, error
