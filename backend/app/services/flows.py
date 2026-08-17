"""수급 동향 — 국내 종목의 투자자별 매매·공매도·신용·대차·프로그램매매를 한 벌로 모은다.

기획서가 이 기능을 특별히 지목했다: *"수급 동향과 랭킹은 예상 밖의 수확이라 화면 기획에
반영할 가치가 있다"*. 토스가 다섯 경로로 주는데 새 키가 필요 없다.

**다섯 표를 나열하지 않는다.** 종목 상세는 이미 길고, 원자료를 그대로 늘어놓으면 읽히지
않는다. 실무자가 실제로 보는 순서로 압축했다:

  1. 투자자별 순매수 — 개인·외국인·기관. 수급의 머리기사다.
  2. 공매도 비중     — 매도 압력
  3. 신용융자 잔고율 — 반대매매 위험
  4. 대차 잔고       — 공매도 여력
  5. 프로그램 순매수 — 차익·비차익 합계

**자료마다 갱신 시각이 다르다**(응답의 `updatedAt` 으로 확인):
공매도·대차거래는 당일 18~19시, 신용거래·투자자별은 다음 영업일 04시.
그래서 같은 날짜에 어떤 것은 있고 어떤 것은 없을 수 있다 — **항목마다 기준일을 따로 들고
화면에 보여준다.** 하나의 날짜로 뭉뚱그리면 없는 자료를 있는 것처럼 보이게 된다.

**한 경로가 실패해도 나머지는 돌려준다.** 다섯 중 하나가 없다고 수급 블록 전체가 사라지면
사용자는 기능이 고장 났다고 여긴다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.clients.toss import TossClient, TossError

logger = logging.getLogger(__name__)

# 화면에 보여줄 거래일 수. 5거래일이면 한 주의 흐름이 보이고 표가 길어지지 않는다.
DEFAULT_DAYS = 5
MAX_DAYS = 20

# 하루 한 번 갱신되는 자료다. 같은 종목을 연달아 열 때만 재호출을 막는다.
CACHE_TTL_SEC = 300.0


def _num(value: object) -> Decimal | None:
    """토스는 수량·금액을 문자열로 준다. Decimal 로 받아 소수 오차를 피한다."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def _pct(value: object) -> str | None:
    """비율은 0.0588 처럼 소수로 온다. 100을 곱하지 않으면 "공매도 0.06%" 가 된다."""
    n = _num(value)
    return None if n is None else f"{n * 100:.2f}"


@dataclass
class InvestorDay:
    """투자자별 순매수 하루치. 단위는 **주**다(금액이 아니다)."""

    date: str
    individual: int | None
    foreigner: int | None
    institution: int | None


@dataclass
class Metric:
    """단일 지표 한 줄. 항목마다 기준일이 다를 수 있어 날짜를 함께 든다."""

    label: str
    value: str
    unit: str = ""
    as_of: str = ""
    note: str = ""


@dataclass
class Flows:
    symbol: str
    investors: list[InvestorDay] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.investors and not self.metrics


# ---------------------------------------------------------------- 정규화 (순수 함수)


def parse_investors(records: list[dict]) -> list[InvestorDay]:
    """투자자별 매매동향 → 날짜별 순매수. 최신순으로 온 순서를 유지한다."""
    days: list[InvestorDay] = []
    for row in records:
        date = (row.get("date") or "").strip()
        if not date:
            continue
        days.append(
            InvestorDay(
                date=date,
                individual=_int((row.get("individual") or {}).get("netBuyVolume")),
                foreigner=_int((row.get("foreigner") or {}).get("netBuyVolume")),
                institution=_int((row.get("institution") or {}).get("netBuyVolume")),
            )
        )
    return days


def parse_short_selling(records: list[dict]) -> Metric | None:
    """가장 최근 공매도 비중."""
    for row in records:
        rate = _pct(row.get("shortSellingVolumeRate"))
        if rate is None:
            continue
        return Metric(
            label="공매도 비중",
            value=rate,
            unit="%",
            as_of=(row.get("date") or "").strip(),
            note="거래량 기준",
        )
    return None


def parse_credit(records: list[dict]) -> Metric | None:
    """신용융자 잔고율. 반대매매 위험을 보는 지표다."""
    for row in records:
        loan = row.get("marginLoan") or {}
        rate = _pct(loan.get("balanceRate"))
        if rate is None:
            continue
        return Metric(
            label="신용융자 잔고율",
            value=rate,
            unit="%",
            as_of=(row.get("date") or "").strip(),
            note="상장주식수 대비",
        )
    return None


def parse_lending(records: list[dict]) -> Metric | None:
    """대차 잔고 수량. 공매도 여력을 보는 지표다."""
    for row in records:
        qty = _int(row.get("balanceQuantity"))
        if qty is None:
            continue
        return Metric(
            label="대차 잔고",
            value=f"{qty:,}",
            unit="주",
            as_of=(row.get("date") or "").strip(),
        )
    return None


def parse_program(records: list[dict]) -> Metric | None:
    """프로그램 순매수 = 차익 + 비차익. 둘을 나눠 보여줄 만큼 자리가 없다."""
    for row in records:
        arb = _int((row.get("arbitrage") or {}).get("netBuyVolume"))
        non_arb = _int((row.get("nonArbitrage") or {}).get("netBuyVolume"))
        if arb is None and non_arb is None:
            continue
        total = (arb or 0) + (non_arb or 0)
        return Metric(
            label="프로그램 순매수",
            value=f"{total:+,}",
            unit="주",
            as_of=(row.get("date") or "").strip(),
            note="차익 + 비차익",
        )
    return None


# ---------------------------------------------------------------- 조회


_cache: dict[tuple[str, int], tuple[float, Flows]] = {}


async def get_flows(symbol: str, *, days: int = DEFAULT_DAYS) -> Flows:
    """수급 한 벌. 다섯 경로를 동시에 부르고, 실패한 것만 빼고 돌려준다."""
    symbol = symbol.strip()
    days = min(max(days, 1), MAX_DAYS)

    key = (symbol, days)
    cached = _cache.get(key)
    if cached and (time.monotonic() - cached[0]) < CACHE_TTL_SEC:
        return cached[1]

    flows = Flows(symbol=symbol)

    async with TossClient() as toss:
        # 같은 rate limit 그룹(초당 10회)이라 다섯 개를 한꺼번에 불러도 상한 안이다.
        # 토큰 버킷이 클라이언트 안에 있어 순서를 여기서 조절할 필요가 없다.
        results = await asyncio.gather(
            toss.get_investor_trading(symbol, count=days),
            toss.get_short_selling(symbol, count=days),
            toss.get_credit_trades(symbol, count=days),
            toss.get_securities_lending(symbol, count=days),
            toss.get_program_trades(symbol, count=days),
            return_exceptions=True,
        )

    labels = ["투자자별 매매동향", "공매도", "신용거래", "대차거래", "프로그램매매"]
    records: list[list[dict]] = []
    for label, result in zip(labels, results):
        if isinstance(result, TossError):
            flows.errors.append(f"{label}: {result}")
            records.append([])
        elif isinstance(result, BaseException):
            # 예상하지 못한 예외는 삼키지 않고 로그에 남긴다. 화면에는 간단히 알린다.
            logger.exception("수급 조회 실패 (%s / %s)", symbol, label)
            flows.errors.append(f"{label}: 조회 중 오류가 발생했습니다.")
            records.append([])
        else:
            records.append(result)

    investor_rows, short_rows, credit_rows, lending_rows, program_rows = records

    flows.investors = parse_investors(investor_rows)
    for metric in (
        parse_short_selling(short_rows),
        parse_credit(credit_rows),
        parse_lending(lending_rows),
        parse_program(program_rows),
    ):
        if metric is not None:
            flows.metrics.append(metric)

    # 전부 실패했으면 캐시하지 않는다 — 다음 요청에서 다시 시도할 기회를 남긴다.
    if not flows.is_empty:
        _cache[key] = (time.monotonic(), flows)
    return flows
