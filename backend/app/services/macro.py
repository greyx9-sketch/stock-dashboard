"""매크로 스트립 — 화면 상단 띠에 쓸 지표 7개를 모은다.

세 곳에서 온다. 갱신 주기가 전혀 달라서 캐시를 따로 둔다.

| 지표 | 출처 | 갱신 |
| --- | --- | --- |
| 코스피 · 코스닥 | 토스 시장지표 | 장중 실시간 |
| SPY (S&P500 추종 ETF) | 토스 미국 시세 | 미국장 중 실시간 |
| 원/달러 | 토스 환율 | 5분 단위 |
| 한국 기준금리 · 미국 기준금리 | 시황 프로젝트 피드 | 하루 1회 |
| WTI 유가 | FRED | 하루 1회 |

**한 곳이 죽어도 나머지는 보여준다.** 스트립이 통째로 비면 사이트가 고장 난 것처럼
보이는데, 실제로는 지표 하나가 안 온 것뿐인 경우가 대부분이다. 그래서 항목별로
성공/실패를 따로 담고, 마지막으로 성공한 값을 DB 에 남겨 두었다가 그것을 보여준다.

**S&P500 은 지수가 아니라 SPY(추종 ETF)다.** 토스 시장지표는 국내 지수만 제공한다.
등락률은 사실상 같지만 값이 지수가 아니므로 화면에 그대로 밝힌다 — 숨기면 틀린 값이 된다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.clients.fred import FredClient, FredError
from app.clients.macro_feed import MacroFeedClient, MacroFeedError
from app.clients.toss import TossClient, TossError
from app.models.base import get_session
from app.models.macro import MacroValue

logger = logging.getLogger(__name__)

# 토스에서 오는 것은 장중에 계속 바뀐다. 화면이 5초마다 물어도 토스를 5초마다 부르지
# 않도록 짧게 캐시한다(기존 시세 폴러와 같은 사고방식).
FAST_TTL_SEC = 10.0
# 시황·FRED 는 하루 한 번 갱신된다. 6시간이면 충분하고, 실패해도 DB 값으로 버틴다.
SLOW_TTL_SEC = 6 * 3600.0

KR_INDEX_SYMBOLS = ["KOSPI", "KOSDAQ"]
SP500_PROXY = "SPY"

# 시황 피드에서 쓸 지표. 키는 그쪽 series id 다.
FEED_PICKS = {
    "bok_base_rate": ("한국 기준금리", "policy_kr"),
    "fed_funds_upper": ("미국 기준금리", "policy_us"),
}


@dataclass
class MacroItem:
    """스트립 한 칸."""

    code: str
    label: str
    value: str  # 화면에 그대로 쓸 문자열. 서버에서 반올림해 보낸다.
    unit: str = ""  # "" / "원" / "%" / "$"
    change_rate: str | None = None  # 등락률(%) 문자열. 없으면 None
    as_of: str = ""  # 기준 시각·날짜
    source: str = ""
    note: str = ""  # 화면에 밝혀야 할 단서 (예: SPY 는 지수가 아님)
    stale: bool = False  # 지금 못 받아서 저장된 값을 보여주는 중


@dataclass
class MacroStrip:
    items: list[MacroItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 캐시


@dataclass
class _Cache:
    items: list[MacroItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    at: float = 0.0

    def fresh(self, ttl: float) -> bool:
        return bool(self.items) and (time.monotonic() - self.at) < ttl


_fast = _Cache()
_slow = _Cache()
_lock = asyncio.Lock()


# ---------------------------------------------------------------- 저장 (버팀목)


def _remember(items: list[MacroItem]) -> None:
    """마지막으로 성공한 값을 남긴다. 다음에 못 받았을 때 이걸 보여준다."""
    if not items:
        return
    now = datetime.now(timezone.utc)
    rows = [
        {
            "code": i.code,
            "label": i.label,
            "value": i.value,
            "unit": i.unit,
            "change_rate": i.change_rate or "",
            "as_of": i.as_of,
            "source": i.source,
            "note": i.note,
            "fetched_at": now,
        }
        for i in items
        if not i.stale  # 저장된 값을 다시 저장하면 기준 시각이 갱신돼 신선해 보인다
    ]
    if not rows:
        return
    updatable = [c for c in rows[0] if c != "code"]
    with get_session() as session:
        stmt = sqlite_insert(MacroValue).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"],
            set_={c: getattr(stmt.excluded, c) for c in updatable},
        )
        session.execute(stmt)
        session.commit()


def _recall(codes: list[str]) -> list[MacroItem]:
    """저장된 값을 꺼낸다. 못 받은 지표 자리를 메우는 용도다."""
    if not codes:
        return []
    with get_session() as session:
        rows = list(
            session.execute(select(MacroValue).where(MacroValue.code.in_(codes))).scalars()
        )
    return [
        MacroItem(
            code=r.code,
            label=r.label,
            value=r.value,
            unit=r.unit,
            change_rate=r.change_rate or None,
            as_of=r.as_of,
            source=r.source,
            note=r.note,
            stale=True,
        )
        for r in rows
    ]


# ---------------------------------------------------------------- 값 다듬기


def _num(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _fmt(value: Decimal, places: int) -> str:
    return f"{value:,.{places}f}"


def _rate(last: Decimal, base: Decimal) -> str | None:
    if base == 0:
        return None
    return f"{(last - base) / base * 100:+.2f}"


# ---------------------------------------------------------------- 토스 (빠른 것)


async def _prev_close(candles: list[dict]) -> Decimal | None:
    """전일 종가. 캔들은 최신순으로 오므로 [0] 이 오늘, [1] 이 전일이다."""
    if len(candles) < 2:
        return None
    return _num(candles[1].get("closePrice"))


async def _fetch_fast() -> tuple[list[MacroItem], list[str]]:
    items: list[MacroItem] = []
    errors: list[str] = []

    async with TossClient() as toss:
        # 국내 지수. 지표 현재가에는 기준가도 등락률도 없고 `timestamp` 도 항상 null 이라,
        # 등락률은 캔들의 전일 종가로 직접 계산한다.
        try:
            prices = await toss.get_market_indicators(KR_INDEX_SYMBOLS)
            latest = {p.get("symbol"): p for p in prices}
            for symbol, label in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
                last = _num((latest.get(symbol) or {}).get("lastPrice"))
                if last is None:
                    errors.append(f"{label} 현재가를 받지 못했습니다.")
                    continue
                change = None
                try:
                    base = await _prev_close(await toss.get_indicator_candles(symbol, count=2))
                    if base is not None:
                        change = _rate(last, base)
                except TossError as exc:
                    logger.warning("%s 등락률 계산 실패: %s", label, exc)
                items.append(
                    MacroItem(
                        code=symbol.lower(),
                        label=label,
                        value=_fmt(last, 2),
                        change_rate=change,
                        # 지표 응답의 timestamp 는 항상 null 이다. 없는 시각을 지어내지 않는다.
                        as_of="",
                        source="토스증권",
                    )
                )
        except TossError as exc:
            errors.append(f"국내 지수: {exc}")

        # S&P500 대용 — 토스 시장지표는 국내 지수만 주므로 추종 ETF 를 쓴다.
        # 종목 현재가에도 기준가가 없다(랭킹에만 있다). 랭킹 상위권에 늘 있으리라 기대하는
        # 대신, 국내 지수와 같은 방식으로 캔들에서 전일 종가를 얻는다.
        try:
            us = await toss.get_prices([SP500_PROXY])
            row = us[0] if us else {}
            last = _num(row.get("lastPrice"))
            if last is None:
                errors.append("SPY 현재가를 받지 못했습니다.")
            else:
                change = None
                try:
                    base = await _prev_close(await toss.get_candles(SP500_PROXY, count=2))
                    if base is not None:
                        change = _rate(last, base)
                except TossError as exc:
                    logger.warning("SPY 등락률 계산 실패: %s", exc)
                items.append(
                    MacroItem(
                        code="sp500_proxy",
                        label="S&P500",
                        value=_fmt(last, 2),
                        unit="$",
                        change_rate=change,
                        as_of=row.get("timestamp") or "",
                        source="토스증권",
                        note="지수가 아니라 추종 ETF(SPY) 가격입니다.",
                    )
                )
        except TossError as exc:
            errors.append(f"S&P500(SPY): {exc}")

        # 환율
        try:
            fx = await toss.get_exchange_rate("USD", "KRW")
            rate = _num(fx.get("rate"))
            if rate is None:
                errors.append("원/달러 환율을 받지 못했습니다.")
            else:
                items.append(
                    MacroItem(
                        code="usdkrw",
                        label="원/달러",
                        value=_fmt(rate, 1),
                        unit="원",
                        as_of=fx.get("validFrom") or "",
                        source="토스증권",
                        note="매매기준율",
                    )
                )
        except TossError as exc:
            errors.append(f"원/달러: {exc}")

    return items, errors


# ---------------------------------------------------------------- 시황·FRED (느린 것)


async def _fetch_slow() -> tuple[list[MacroItem], list[str]]:
    items: list[MacroItem] = []
    errors: list[str] = []

    # 시황 피드 — 정책금리
    try:
        async with MacroFeedClient() as feed:
            series = await feed.fetch()
        for series_id, (label, code) in FEED_PICKS.items():
            row = series.get(series_id)
            if row is None:
                errors.append(f"{label}: 피드에 없습니다.")
                continue
            # 비율은 0.0275 처럼 소수로 온다. 100을 곱하지 않으면 0.03% 로 뜬다.
            value = row.value * 100 if row.is_ratio else row.value
            items.append(
                MacroItem(
                    code=code,
                    label=label,
                    value=f"{value:,.2f}",
                    unit="%",
                    as_of=row.ref_date,
                    source="한국은행·FRED (시황)",
                )
            )
    except MacroFeedError as exc:
        errors.append(f"매크로 피드: {exc}")

    # FRED — WTI 유가
    try:
        async with FredClient() as fred:
            wti = await fred.get_wti()
        items.append(
            MacroItem(
                code="wti",
                label="WTI 유가",
                value=f"{wti.value:,.2f}",
                unit="$",
                as_of=wti.date,
                source="FRED",
            )
        )
    except (FredError, RuntimeError) as exc:
        # RuntimeError = config.require() — FRED 키가 아직 없다. 오류로 남기되 멈추지 않는다.
        errors.append(f"WTI 유가: {exc}")

    return items, errors


# ---------------------------------------------------------------- 조립


# 화면에 보일 순서. 국내 → 미국 → 환율 → 정책금리 → 원자재.
ORDER = ["kospi", "kosdaq", "sp500_proxy", "usdkrw", "policy_kr", "policy_us", "wti"]


async def get_strip() -> MacroStrip:
    """스트립 한 벌. 캐시가 신선하면 외부를 부르지 않는다."""
    async with _lock:
        errors: list[str] = []

        if _fast.fresh(FAST_TTL_SEC):
            fast_items = _fast.items
            errors += _fast.errors
        else:
            fast_items, fast_errors = await _fetch_fast()
            if fast_items:
                _fast.items, _fast.errors, _fast.at = fast_items, fast_errors, time.monotonic()
            errors += fast_errors

        if _slow.fresh(SLOW_TTL_SEC):
            slow_items = _slow.items
            errors += _slow.errors
        else:
            slow_items, slow_errors = await _fetch_slow()
            if slow_items:
                _slow.items, _slow.errors, _slow.at = slow_items, slow_errors, time.monotonic()
            errors += slow_errors

        items = fast_items + slow_items
        await asyncio.to_thread(_remember, items)

        # 못 받은 자리는 저장된 값으로 메운다. 스트립이 통째로 비는 것을 막는다.
        got = {i.code for i in items}
        missing = [c for c in ORDER if c not in got]
        if missing:
            items += await asyncio.to_thread(_recall, missing)

        items.sort(key=lambda i: ORDER.index(i.code) if i.code in ORDER else len(ORDER))
        return MacroStrip(items=items, errors=errors)
