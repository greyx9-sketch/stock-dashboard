"""10-Q 에서 분기 재무를 뽑는다.

**새 호출이 없다.** companyfacts 응답 하나에 연간·분기가 다 들어 있어서, 연간 재무를
받을 때 이미 내려받은 자료를 다시 훑기만 한다.

## 10-Q 사실의 모양 (2026-08-25 원문 확인)

애플 `NetIncomeLoss` 를 예로 들면:

    start        end          일수   fy    fp    값
    2025-09-28   2025-12-27    90   2026  Q1   42.10십억   ← 1분기 3개월
    2025-12-28   2026-03-28    90   2026  Q2   29.58십억   ← 2분기 3개월
    2025-09-28   2026-03-28   181   2026  Q2   71.67십억   ← 상반기 누적
    2025-09-28   2026-06-27   272   2026  Q3  101.46십억   ← 9개월 누적

국내 DART 와 똑같은 구조다 — 3개월치와 누적이 함께 온다. **기간 길이로 가른다.**

## 함정 둘

**1. 같은 `(회계연도, 분기)` 태그에 두 기간이 들어온다.**

10-Q 는 '전년 동기'를 나란히 싣는데, 그 비교분에도 **보고서의 회계연도**가 붙는다.
그래서 `fy=2026, fp=Q1` 을 달고 오는 사실이 둘이다:

    2025-09-28 ~ 2025-12-27   ← 진짜 FY2026 1분기
    2024-09-29 ~ 2024-12-28   ← FY2025 1분기의 비교분 (같은 태그를 달고 있다)

**기간이 늦은 쪽이 당기다.** 처음엔 '나중에 제출된 것'을 골랐는데, 비교분이 늘 더
나중에 제출되므로 그쪽이 이겨서 **분기가 한 해씩 밀렸다.** 재무상태표도 같은 이유로
직전 연도말 잔액이 들어와, 한 회계연도의 세 분기가 전부 같은 자산총계를 갖고 있었다.
(2026-08-25 실측에서 잡았다.)

**2. 회계연도가 회사마다 다르다.**

애플 FY2026 은 2025년 9월에 시작하고, 마이크로소프트 FY2026 은 2025년 7월에 시작한다.
그래서 **종료일에서 회계연도를 계산하지 않고** 사실이 들고 있는 `fy` 를 쓴다. 종료일로
계산하면 애플 FY2026 1분기(2025-12-27 종료)가 2025년으로 들어가, 이미 있는 FY2025
연간 행과 겹친다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.base import get_session
from app.models.us_quarterly import SecQuarterly
from app.services.sec_financials import (
    DURATION_CONCEPTS,
    INSTANT_CONCEPTS,
    _pick_latest,
    pad_cik,
)


logger = logging.getLogger(__name__)

# 3개월 기간으로 볼 일수 범위. 회사마다 결산 요일이 달라 89~92일로 흔들린다.
MIN_QUARTER_DAYS = 80
MAX_QUARTER_DAYS = 100

# 누적 기간은 분기 수 × 한 분기(약 91일)다. 넉넉히 잡아 맞춘다.
CUMULATIVE_DAYS = {2: (170, 195), 3: (260, 285)}

QUARTERS = (1, 2, 3)

INCOME_METRICS = tuple(DURATION_CONCEPTS)
BALANCE_METRICS = tuple(INSTANT_CONCEPTS)


@dataclass(frozen=True)
class QuarterFacts:
    fiscal_year: int
    quarter: int
    period_end: str
    values: dict[str, int | None]
    accession_no: str
    filed_date: str


def _pick_current(facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """같은 태그를 단 사실들 중 **그 분기의 당기**를 고른다.

    **기간이 가장 늦은 것**이다. 전년 비교분은 언제나 더 이른 기간이고, 제출 시점으로
    고르면 오히려 비교분이 이긴다(파일 첫머리 "함정 둘" 참고).

    기간이 같으면 나중에 제출된 것을 쓴다 — 재작성된 값이 맞다.
    """
    if not facts:
        return None
    return max(
        facts, key=lambda f: (f.get("end") or "", f.get("filed") or "", f.get("accn") or "")
    )


def _days(fact: dict[str, Any]) -> int | None:
    start, end = fact.get("start"), fact.get("end")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _is_quarterly_report(form: str) -> bool:
    """10-Q 와 그 정정본만 본다."""
    return form.startswith("10-Q")


def _period_of(fact: dict[str, Any]) -> tuple[int, int] | None:
    """이 사실이 어느 회계연도 몇 분기 것인지. 알 수 없으면 None.

    **종료일로 계산하지 않고 `fy`·`fp` 를 그대로 쓴다** — 회계연도가 회사마다 달라서다
    (파일 첫머리 "함정 둘" 참고).
    """
    fy, fp = fact.get("fy"), fact.get("fp")
    if not isinstance(fy, int) or not isinstance(fp, str) or not fp.startswith("Q"):
        return None
    try:
        quarter = int(fp[1:])
    except ValueError:
        return None
    return (fy, quarter) if quarter in QUARTERS else None


def _collect_periods(
    us_gaap: dict[str, Any], concepts: tuple[str, ...], *, cumulative: bool
) -> dict[tuple[int, int], dict[str, Any]]:
    """(회계연도, 분기) → 사실. 기간 길이로 3개월치와 누적을 가른다."""
    found: dict[tuple[int, int], list[dict[str, Any]]] = {}

    for concept in concepts:
        entry = us_gaap.get(concept)
        if not entry:
            continue
        for fact in (entry.get("units") or {}).get("USD") or []:
            if not _is_quarterly_report(fact.get("form") or ""):
                continue
            period = _period_of(fact)
            if period is None:
                continue
            _, quarter = period
            days = _days(fact)
            if days is None:
                continue

            if cumulative:
                # 1분기는 누적과 3개월이 같은 기간이다 — 정의상 같으므로 그대로 쓴다.
                low, high = CUMULATIVE_DAYS.get(quarter, (MIN_QUARTER_DAYS, MAX_QUARTER_DAYS))
            else:
                low, high = MIN_QUARTER_DAYS, MAX_QUARTER_DAYS
            if not low <= days <= high:
                continue

            found.setdefault(period, []).append(fact)

        # 앞선 계정에서 찾은 기간은 덮지 않는다. 우선순위가 앞선 계정이 이긴다.
        if found:
            break

    return {period: _pick_current(facts) for period, facts in found.items() if facts}


def _collect_instants(
    us_gaap: dict[str, Any], concepts: tuple[str, ...]
) -> dict[tuple[int, int], dict[str, Any]]:
    """분기말 잔액. 기간(start)이 붙어 있으면 우리가 찾는 잔액이 아니다."""
    found: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for concept in concepts:
        entry = us_gaap.get(concept)
        if not entry:
            continue
        for fact in (entry.get("units") or {}).get("USD") or []:
            if not _is_quarterly_report(fact.get("form") or "") or fact.get("start"):
                continue
            period = _period_of(fact)
            if period is not None:
                found.setdefault(period, []).append(fact)
        if found:
            break
    return {period: _pick_current(facts) for period, facts in found.items() if facts}


def extract_quarters(facts: dict[str, Any]) -> list[QuarterFacts]:
    """companyfacts 에서 분기 재무를 뽑는다. 오래된 분기부터 돌려준다."""
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    if not us_gaap:
        return []

    collected: dict[str, dict[tuple[int, int], dict[str, Any]]] = {}
    for metric, concepts in DURATION_CONCEPTS.items():
        collected[metric] = _collect_periods(us_gaap, concepts, cumulative=False)
        collected[f"{metric}_cum"] = _collect_periods(us_gaap, concepts, cumulative=True)
    for metric, concepts in INSTANT_CONCEPTS.items():
        collected[metric] = _collect_instants(us_gaap, concepts)

    # 태그마다 당기 사실을 이미 골라 두었으므로(위 `_pick_current`) 키를 그대로 쓴다.
    valid = {period for periods in collected.values() for period in periods}

    results: list[QuarterFacts] = []
    for period in sorted(valid):
        values = {
            metric: (periods.get(period) or {}).get("val") for metric, periods in collected.items()
        }
        if all(v is None for v in values.values()):
            continue

        sources = [p.get(period) for p in collected.values() if p.get(period)]
        newest = _pick_latest([s for s in sources if s]) or {}
        end_source = collected["net_income"].get(period) or collected["revenue"].get(period) or newest

        results.append(
            QuarterFacts(
                fiscal_year=period[0],
                quarter=period[1],
                period_end=end_source.get("end", ""),
                values=values,
                accession_no=newest.get("accn", ""),
                filed_date=newest.get("filed", ""),
            )
        )
    return results


def _save(cik: str, quarters: list[QuarterFacts]) -> int:
    if not quarters:
        return 0
    rows = [
        {
            "cik": cik,
            "fiscal_year": q.fiscal_year,
            "quarter": q.quarter,
            "period_end": q.period_end,
            **q.values,
            "currency": "USD",
            "accession_no": q.accession_no,
            "filed_date": q.filed_date,
        }
        for q in quarters
    ]
    keys = ("cik", "fiscal_year", "quarter")
    updatable = [c for c in rows[0] if c not in keys]

    with get_session() as session:
        stmt = sqlite_insert(SecQuarterly).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(keys),
            set_={c: getattr(stmt.excluded, c) for c in updatable},
        )
        session.execute(stmt)
        session.commit()
    return len(rows)


def stored_count(cik: str) -> int:
    with get_session() as session:
        return len(
            list(
                session.execute(
                    select(SecQuarterly.quarter).where(SecQuarterly.cik == pad_cik(cik))
                ).scalars()
            )
        )


def load(cik: str, limit: int = 12) -> list[SecQuarterly]:
    """저장된 분기를 **오래된 것부터**. 차트가 그대로 그릴 수 있는 순서다."""
    with get_session() as session:
        rows = list(
            session.execute(
                select(SecQuarterly)
                .where(SecQuarterly.cik == pad_cik(cik))
                .order_by(SecQuarterly.fiscal_year.desc(), SecQuarterly.quarter.desc())
                .limit(limit)
            ).scalars()
        )
    rows.reverse()
    return rows


async def ensure_quarters(cik: str, *, minimum: int = 8) -> int:
    """분기 재무를 채운다. 이미 충분하면 부르지 않는다.

    **연간 재무와 같은 응답을 쓴다.** companyfacts 는 회사당 3~4MB 라 두 번 받지 않는
    것이 중요하다 — 연간을 먼저 받아 두었다면 그때 같이 채우는 편이 낫지만, 분기를
    나중에 붙였으므로 여기서 한 번 더 받는 경우가 생긴다. 한 번 채우면 그만이다.
    """
    from app.clients.sec import SecClient

    cik = pad_cik(cik)
    if stored_count(cik) >= minimum:
        return 0

    async with SecClient() as sec:
        facts = await sec.get_company_facts(cik)

    extracted = extract_quarters(facts)
    if not extracted:
        logger.info("CIK %s: 10-Q 에서 분기 재무를 찾지 못했다", cik)
        return 0

    return await asyncio.to_thread(_save, cik, extracted)
