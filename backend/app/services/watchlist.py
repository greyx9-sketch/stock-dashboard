"""관심종목 — 목록 관리와 기준가 해결.

목록 자체는 DB 한 테이블이라 단순하다. 손이 가는 곳은 **기준가**다. 등락률을 보여주려면
"무엇 대비인가"가 있어야 하는데, 그 출처가 시장마다 다르다.

| 시장 | 기준가 | 왜 |
| --- | --- | --- |
| 국내 | KRX 확정 종가 (DB) | 토스 일봉 종가는 시간외 체결이 섞여 앱 화면과 어긋난다 |
| 미국 | 토스 일봉의 직전 봉 종가 | 미국에는 KRX 같은 별도 확정 종가 소스가 없다 |

국내를 일봉으로 통일하면 목록 화면과 상세 화면의 등락률이 서로 달라진다. 삼성전자
2026-08-13 을 예로 들면 KRX 확정 종가는 268,000 인데 토스 일봉 종가는 263,000 이다.
같은 화면에서 두 숫자가 다르면 사용자는 어느 쪽을 믿어야 할지 알 수 없다.

**일봉은 시작된 세션에만 생긴다**(실측 확인). 그래서 `candles[1]` 이 장중에는 "전일",
마감 후에는 "마지막 거래일의 전일"이 되어 양쪽 다 맞는다 — 마감 후에 등락률 0% 가
아니라 마지막 세션의 등락률이 보이는 것이 사용자가 기대하는 모습이다.

미국 기준가는 캐시한다(종목마다 호출 하나라 목록이 길면 느려진다). **세션이 막 열린
직후 최대 몇 분간은 기준가가 전 세션 것일 수 있다.** 그래서 화면에 기준일을 함께 보여준다 —
틀린 값을 조용히 보여주는 것보다 사용자가 눈으로 알아채는 편이 낫다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select

from app.clients.toss import TossClient, TossError
from app.models.base import get_session
from app.models.quote import KrxDailyQuote
from app.models.watchlist import WatchlistItem
from app.services.price_poller import classify_market

logger = logging.getLogger(__name__)

# 담을 수 있는 종목 수. 폴러가 한 번에 부르는 상한(200)보다 훨씬 적게 둔다 —
# 사람이 눈으로 훑는 목록이고, 200 줄짜리 관심종목은 관심종목이 아니다.
MAX_ITEMS = 60

# 미국 기준가 캐시 수명(초).
US_BASE_TTL_SEC = 300.0

DEFAULT_GROUP = "기본"


class WatchlistError(Exception):
    """사용자에게 그대로 보여줄 수 있는 실패."""


@dataclass
class Item:
    symbol: str
    market: str
    name: str
    group_name: str
    sort_order: int
    base_price: Decimal | None = None
    base_date: str = ""
    base_source: str = ""


def _num(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalize_symbol(raw: str) -> str:
    """입력을 저장 형태로 맞춘다.

    미국 티커는 대문자로 통일한다. `aapl` 과 `AAPL` 이 각각 담기면 같은 종목이 두 줄이 된다.
    국내 코드는 숫자라 대소문자가 없다.
    """
    return raw.strip().upper()


# ---------------------------------------------------------------- 목록 읽기·쓰기


def _rows() -> list[WatchlistItem]:
    stmt = select(WatchlistItem).order_by(WatchlistItem.sort_order, WatchlistItem.symbol)
    with get_session() as session:
        return list(session.execute(stmt).scalars())


def _krx_bases(symbols: list[str]) -> dict[str, KrxDailyQuote]:
    """국내 종목의 가장 최근 확정 시세. 종목마다 최신 거래일이 다를 수 있어 종목별로 구한다.

    (거래정지·신규상장 종목은 전체 최신일에 행이 없다. 전체 최신일 하나로 뭉뚱그리면
    그런 종목의 기준가가 비어 버린다.)
    """
    if not symbols:
        return {}

    latest = (
        select(KrxDailyQuote.symbol, func.max(KrxDailyQuote.trade_date).label("trade_date"))
        .where(KrxDailyQuote.symbol.in_(symbols))
        .group_by(KrxDailyQuote.symbol)
        .subquery()
    )
    stmt = select(KrxDailyQuote).join(
        latest,
        (KrxDailyQuote.symbol == latest.c.symbol)
        & (KrxDailyQuote.trade_date == latest.c.trade_date),
    )
    with get_session() as session:
        return {row.symbol: row for row in session.execute(stmt).scalars()}


def pick_base(candles: list[dict]) -> tuple[Decimal, str] | None:
    """일봉 목록에서 기준가를 고른다. 최신순으로 온다 — **[0] 이 아니라 [1]** 이다.

    [0] 은 진행 중인 세션(장중)이거나 마지막으로 끝난 세션(마감 후)이다. 어느 쪽이든
    "지금 값과 비교할 대상"은 그 앞의 봉이다. 일봉은 시작된 세션에만 생기므로
    이 규칙 하나가 장중과 마감 후 양쪽에서 맞는다.
    """
    if len(candles) < 2:
        return None
    close = _num(candles[1].get("closePrice"))
    if close is None:
        return None
    return close, (candles[1].get("timestamp") or "")[:10]


# 미국 기준가 캐시. symbol → (받은 시각, 종가, 그 봉의 날짜)
_us_base_cache: dict[str, tuple[float, Decimal, str]] = {}


async def _us_bases(symbols: list[str]) -> dict[str, tuple[Decimal, str]]:
    """미국 종목의 기준가(직전 일봉 종가)를 모은다. 실패한 종목은 빠진 채로 온다."""
    if not symbols:
        return {}

    now = time.monotonic()
    result: dict[str, tuple[Decimal, str]] = {}
    stale = []
    for symbol in symbols:
        cached = _us_base_cache.get(symbol)
        if cached and (now - cached[0]) < US_BASE_TTL_SEC:
            result[symbol] = (cached[1], cached[2])
        else:
            stale.append(symbol)

    if not stale:
        return result

    async with TossClient() as toss:
        # 종목마다 호출 하나다. 캔들 그룹의 초당 한도는 클라이언트 안 토큰 버킷이 지킨다.
        fetched = await asyncio.gather(
            *(toss.get_candles(s, interval="1d", count=3) for s in stale),
            return_exceptions=True,
        )

    for symbol, candles in zip(stale, fetched):
        if isinstance(candles, TossError):
            logger.warning("미국 기준가 조회 실패 (%s): %s", symbol, candles)
            continue
        if isinstance(candles, BaseException):
            logger.exception("미국 기준가 조회 중 오류 (%s)", symbol)
            continue
        picked = pick_base(candles)
        if picked is None:
            continue
        close, date = picked
        _us_base_cache[symbol] = (time.monotonic(), close, date)
        result[symbol] = (close, date)

    return result


async def list_items() -> list[Item]:
    """관심종목 목록. 기준가까지 채워 돌려준다.

    기준가를 못 구한 종목도 목록에서 빼지 않는다. 이름과 현재가는 그대로 보이고
    등락률 자리만 비는 편이 낫다 — 담은 종목이 목록에서 사라지면 고장으로 읽힌다.
    """
    rows = _rows()
    kr = [r.symbol for r in rows if r.market == "KR"]
    us = [r.symbol for r in rows if r.market == "US"]

    kr_bases = _krx_bases(kr)
    us_bases = await _us_bases(us)

    items: list[Item] = []
    for row in rows:
        item = Item(
            symbol=row.symbol,
            market=row.market,
            name=row.name,
            group_name=row.group_name,
            sort_order=row.sort_order,
        )
        if row.market == "KR":
            quote = kr_bases.get(row.symbol)
            if quote is not None:
                item.base_price = Decimal(quote.close)
                item.base_date = quote.trade_date
                item.base_source = "KRX 확정 종가"
        else:
            found = us_bases.get(row.symbol)
            if found is not None:
                item.base_price, item.base_date = found
                item.base_source = "토스 일봉 종가"
        items.append(item)
    return items


async def _resolve_name(symbol: str) -> str:
    """종목명을 토스에서 받아 온다. 국내·미국 모두 한국어 이름이 온다.

    없는 종목을 담는 것을 여기서 걸러낸다 — 토스가 모르는 코드면 담지 않는다.
    """
    async with TossClient() as toss:
        rows = await toss.get_stocks([symbol])
    for row in rows:
        if row.get("symbol") == symbol:
            return (row.get("name") or row.get("englishName") or symbol).strip()
    raise WatchlistError(
        f"'{symbol}' 을 찾을 수 없습니다. 국내는 6자리 종목코드, 미국은 티커로 넣어 주세요."
    )


async def add(raw_symbol: str) -> Item:
    """관심종목에 담는다. 이미 있으면 그대로 돌려준다(두 번 눌러도 안전하다)."""
    symbol = normalize_symbol(raw_symbol)
    if not symbol:
        raise WatchlistError("종목 코드를 넣어 주세요.")

    with get_session() as session:
        existing = session.get(WatchlistItem, symbol)
        if existing is not None:
            return Item(
                symbol=existing.symbol,
                market=existing.market,
                name=existing.name,
                group_name=existing.group_name,
                sort_order=existing.sort_order,
            )
        count = session.execute(select(func.count()).select_from(WatchlistItem)).scalar() or 0

    if count >= MAX_ITEMS:
        raise WatchlistError(
            f"관심종목은 {MAX_ITEMS}개까지 담을 수 있습니다. 하나를 지운 뒤 다시 담아 주세요."
        )

    # 이름 조회는 DB 세션 밖에서 한다. 외부 호출을 세션 안에 두면 응답이 느릴 때
    # SQLite 쓰기 잠금을 그만큼 오래 붙들게 된다.
    name = await _resolve_name(symbol)
    market = classify_market(symbol)

    with get_session() as session:
        # 순서는 맨 뒤로. 방금 담은 것이 목록 위로 끼어들면 보고 있던 자리가 어긋난다.
        top = session.execute(select(func.max(WatchlistItem.sort_order))).scalar()
        row = WatchlistItem(
            symbol=symbol,
            market=market,
            name=name,
            group_name=DEFAULT_GROUP,
            sort_order=(top or 0) + 1,
        )
        session.add(row)
        session.commit()

    return Item(
        symbol=symbol,
        market=market,
        name=name,
        group_name=DEFAULT_GROUP,
        sort_order=row.sort_order,
    )


def remove(raw_symbol: str) -> bool:
    """목록에서 뺀다. 없던 종목이면 False."""
    symbol = normalize_symbol(raw_symbol)
    with get_session() as session:
        row = session.get(WatchlistItem, symbol)
        if row is None:
            return False
        session.delete(row)
        session.commit()
    return True


def move(raw_symbol: str, direction: str) -> None:
    """이웃과 순서를 맞바꾼다.

    순서 값을 다시 매기지 않고 두 줄만 교환한다. 목록 전체를 재정렬하면 그 사이
    다른 줄의 순서까지 흔들릴 수 있고, 실제로 필요한 것은 한 칸 이동뿐이다.
    """
    symbol = normalize_symbol(raw_symbol)
    if direction not in ("up", "down"):
        raise WatchlistError("방향은 up 또는 down 이어야 합니다.")

    with get_session() as session:
        rows = list(
            session.execute(
                select(WatchlistItem).order_by(WatchlistItem.sort_order, WatchlistItem.symbol)
            ).scalars()
        )
        index = next((i for i, r in enumerate(rows) if r.symbol == symbol), None)
        if index is None:
            raise WatchlistError(f"'{symbol}' 은 관심종목에 없습니다.")

        target = index - 1 if direction == "up" else index + 1
        if not 0 <= target < len(rows):
            return  # 이미 맨 위/맨 아래다. 오류로 다룰 일이 아니다.

        here, there = rows[index], rows[target]
        # 순서 값이 같으면(예전 데이터·동시 추가) 교환해도 자리가 바뀌지 않는다.
        # 그럴 때는 정렬 결과의 위치를 기준으로 값을 새로 준다.
        if here.sort_order == there.sort_order:
            for position, row in enumerate(rows):
                row.sort_order = position
            here, there = rows[index], rows[target]
        here.sort_order, there.sort_order = there.sort_order, here.sort_order
        session.commit()
