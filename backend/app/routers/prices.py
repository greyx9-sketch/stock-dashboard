"""현재가 엔드포인트.

화면이 몇 초마다 이 경로를 부른다. **여기서는 외부 API 를 부르지 않는다.**
폴러가 백그라운드에서 받아 둔 캐시를 읽어 돌려줄 뿐이라 항상 즉시 응답한다.

등락률의 기준가는 KRX 확정 종가다. 토스 시세 API 에는 기준가 필드가 없고, 토스 일봉 종가는
시간외 체결이 섞여 있어 앱 화면과 어긋난다. 이 프로젝트가 KRX 확정 종가를 따로 받아 쌓는
이유가 이것이고, 그 결과를 여기서 쓴다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.models.base import get_session
from app.models.quote import KrxDailyQuote
from app.services.price_poller import LIVE_PHASES, poller

router = APIRouter(prefix="/api/prices", tags=["현재가"])

# 한 번에 물어볼 수 있는 종목 수. 토스 상한(200)과 맞춰 둔다.
MAX_SYMBOLS = 200

# 이보다 오래된 캐시는 "낡음"으로 표시한다. 정규장 폴링 간격(5초)의 몇 배로 잡았다.
STALE_AFTER_SEC = 30.0


class MarketOut(BaseModel):
    """지금 장이 어떤 상태인지."""

    phase: str = Field(description="PRE / REGULAR / AFTER / DAY / CLOSED / HOLIDAY / UNKNOWN")
    label: str = Field(description="화면에 그대로 쓸 한국어 이름")
    trade_date: str | None = Field(description="오늘 날짜. 휴장이면 없음")
    next_open: str | None = Field(description="다음 개장 시각")
    session_end: str | None = Field(description="현재 세션 종료 시각")
    is_live: bool = Field(description="지금 값이 움직이는 시간대인가")


class LivePriceOut(BaseModel):
    """종목 하나의 현재가."""

    symbol: str
    last_price: Decimal
    base_price: Decimal | None = Field(description="기준가 — KRX 직전 거래일 확정 종가")
    base_date: str | None = Field(description="기준가의 거래일")
    change: Decimal | None
    change_rate: Decimal | None
    timestamp: str | None = Field(description="토스가 알려준 체결 시각")
    age_seconds: float = Field(description="이 값을 받아 온 지 몇 초 지났는가")
    stale: bool = Field(description="갱신이 끊긴 값인가")


class PricesOut(BaseModel):
    # 국내와 미국은 장 시간이 완전히 다르다. 둘 다 내려주고 화면이 보고 있는 쪽을 고른다.
    # 하나만 주면 한국 애프터마켓(16시)에 미국 화면이 "애프터마켓"으로 뜨는 일이 생긴다.
    markets: dict[str, MarketOut] = Field(description="시장별 장 상태. 키는 KR / US")
    prices: list[LivePriceOut]
    missing: list[str] = Field(description="아직 받아 오지 못한 종목. 다음 요청에는 채워진다")
    error: str | None = Field(description="폴러가 마지막으로 만난 오류. 있으면 화면에 밝힌다")
    last_success_at: str | None = Field(description="마지막으로 현재가를 받아 온 시각")
    realtime: bool = Field(
        description=(
            "이 종목들이 전부 웹소켓 체결 푸시로 들어오고 있는가. 거짓이면 폴링으로 "
            "받는 중이다 — 값은 그대로 나오고 갱신이 덜 촘촘할 뿐이다."
        )
    )


def _base_prices(symbols: list[str]) -> dict[str, KrxDailyQuote]:
    """종목별 가장 최근 확정 시세를 한 번의 질의로 가져온다.

    종목마다 최신 거래일이 다를 수 있다(거래정지·신규상장). 전체 최신일 하나로 뭉뚱그리면
    그런 종목의 기준가가 비어 버리므로 종목별 최댓값을 구한다.
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


@router.get("", summary="현재가 (여러 종목)")
def get_prices(
    symbols: str = Query(
        ...,
        description="종목 코드나 티커를 콤마로 구분. 최대 200개 (예: 005930,000660 / AAPL,KO)",
        # 6 이었다. KRX 종목코드가 6자리라 맞는 값처럼 보였지만, 미국 티커는 KO·AAPL 처럼
        # 6자 미만이라 한 종목만 보고 있을 때 422 로 거절됐다(화면에 "현재가 연결 끊김").
        # 여러 종목이면 콤마 때문에 길어져 우연히 통과하던 탓에 늦게 드러났다.
        min_length=1,
    ),
) -> PricesOut:
    """화면이 주기적으로 부르는 경로. 캐시만 읽으므로 외부 API 를 기다리지 않는다.

    처음 물어본 종목은 아직 캐시에 없어 `missing` 으로 돌아온다. 폴러가 즉시 깨어나
    받아 오므로 다음 요청에는 채워진다.
    """
    wanted = [s.strip() for s in symbols.split(",") if s.strip()][:MAX_SYMBOLS]

    # 화면이 보고 있다고 알린다. 이걸로 폴링 대상이 정해진다.
    poller.register(wanted)
    cached = poller.snapshot(wanted)
    bases = _base_prices(wanted)

    now = datetime.now(timezone.utc)
    prices: list[LivePriceOut] = []
    for symbol in wanted:
        entry = cached.get(symbol)
        if entry is None:
            continue

        base_row = bases.get(symbol)
        base = Decimal(base_row.close) if base_row else None
        change = entry.last_price - base if base is not None else None
        rate = (
            (change / base * 100).quantize(Decimal("0.01"))
            if base is not None and base != 0 and change is not None
            else None
        )
        age = entry.age_seconds(now)

        prices.append(
            LivePriceOut(
                symbol=symbol,
                last_price=entry.last_price,
                base_price=base,
                base_date=base_row.trade_date if base_row else None,
                change=change,
                change_rate=rate,
                timestamp=entry.timestamp,
                age_seconds=round(age, 1),
                stale=age > STALE_AFTER_SEC,
            )
        )

    last_success = poller.last_success_at

    return PricesOut(
        markets={
            country: MarketOut(
                phase=state.phase,
                label=state.label,
                trade_date=state.trade_date,
                next_open=state.next_open,
                session_end=state.session_end,
                is_live=state.phase in LIVE_PHASES,
            )
            for country, state in poller.markets.items()
        },
        prices=prices,
        missing=[s for s in wanted if s not in cached],
        error=poller.last_error,
        last_success_at=last_success.isoformat() if last_success else None,
        realtime=poller.realtime_for(wanted),
    )
