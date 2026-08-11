"""SEC XBRL(companyfacts)에서 연도별 재무를 뽑아 저장한다.

**모든 숫자는 XBRL 사실에서 직접 가져온다.** LLM 은 이 경로에 관여하지 않는다
(CLAUDE.md 절대 규칙 3). 마진·성장률은 저장하지 않고 조회할 때 원값으로 계산한다.

companyfacts 를 실제로 뜯어보며 확인한 함정들:

1. **10-K 안에 분기 데이터가 섞여 있다.** form 이 "10-K" 라고 해서 1년치가 아니다.
   기간 길이(종료일 - 시작일)를 보고 연간만 골라야 한다.

2. **같은 회계연도가 여러 보고서에 나온다.** 2024 회계연도 순이익은 2024년 10-K 에도,
   2025년 10-K 에도 비교표로 들어 있다. 재작성되면 값이 달라진다. 국내(DART)와 같은
   규칙으로 **가장 나중에 제출된 보고서**의 값을 남긴다.

3. **`fy` 필드는 데이터의 연도가 아니다.** 제출 보고서의 회계연도다. 애플 2024 회계연도
   수치가 `fy: 2025` 로 들어오기도 한다. 그래서 연도는 `end`(기간 종료일)로 판단한다.

4. **미국 회사는 12월 결산이 아닌 경우가 흔하다.** 애플 2025 회계연도는
   2024-09-29 ~ 2025-09-27 이다. 1~5월에 끝나는 회사(유통업에 흔하다)는 종료일 연도에서
   한 해를 빼야 통용되는 회계연도 표기와 맞는다.

5. **계정 이름이 회사·연도마다 다르다.** 애플은 최근 매출을
   RevenueFromContractWithCustomerExcludingAssessedTax 로, 예전에는 Revenues 로 태깅했다.
   후보를 우선순위대로 두고 연도별로 값이 있는 것을 쓴다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.clients.sec import SecClient, pad_cik
from app.models.base import get_session
from app.models.us_company import SecFinancial

logger = logging.getLogger(__name__)

# 연간으로 인정할 기간 길이(일). 정확히 365일이 아니다 — 애플처럼 52/53주 회계연도를 쓰는
# 회사는 한 해가 371일이 되기도 한다. 분기(약 90일)와 갈라내는 것이 목적이다.
MIN_ANNUAL_DAYS = 300
MAX_ANNUAL_DAYS = 400

# 회계연도 표기 규칙: 1~5월에 끝나면 앞 해의 회계연도로 본다.
# 1월 말에 끝나는 유통업 회계연도를 그 전해로 부르는 관행에 맞춘 것이다.
FISCAL_YEAR_CUTOFF_MONTH = 6

# 항목별 us-gaap 계정 후보. 앞에서 값을 찾으면 뒤는 보지 않는다.
DURATION_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
}

# 시점 개념(재무상태표)은 기간이 아니라 특정 날짜의 잔액이다. start 가 없다.
INSTANT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "total_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
}

METRICS = tuple(DURATION_CONCEPTS) + tuple(INSTANT_CONCEPTS)


@dataclass
class YearFacts:
    """한 회계연도에 모인 값들."""

    fiscal_year: int
    period_end: str
    values: dict[str, int | None]
    accession_no: str
    filed_date: str


def fiscal_year_of(period_end: str) -> int | None:
    """기간 종료일에서 회계연도를 정한다."""
    try:
        end = date.fromisoformat(period_end)
    except ValueError:
        return None
    return end.year if end.month >= FISCAL_YEAR_CUTOFF_MONTH else end.year - 1


def _is_annual_report(form: str) -> bool:
    """10-K 와 그 정정본(10-K/A)만 연간 보고서로 본다."""
    return form.startswith("10-K")


def _annual_duration(fact: dict[str, Any]) -> bool:
    """기간 사실이 1년치인가. 10-K 에도 분기 사실이 섞여 있어 반드시 걸러야 한다."""
    start, end = fact.get("start"), fact.get("end")
    if not start or not end:
        return False
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return False
    return MIN_ANNUAL_DAYS <= days <= MAX_ANNUAL_DAYS


def _pick_latest(facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """같은 연도의 여러 사실 중 가장 나중에 제출된 것.

    재작성되면 값이 달라지므로 최신 보고서를 따른다.
    """
    if not facts:
        return None
    return max(facts, key=lambda f: (f.get("filed") or "", f.get("accn") or ""))


def _collect(
    us_gaap: dict[str, Any], concepts: tuple[str, ...], *, duration: bool
) -> dict[int, dict[str, Any]]:
    """한 항목에 대해 회계연도 → 사실 을 만든다. 후보 계정을 우선순위대로 훑는다."""
    by_year: dict[int, dict[str, Any]] = {}

    for concept in concepts:
        entry = us_gaap.get(concept)
        if not entry:
            continue
        # 통화는 USD 만 쓴다. 다른 통화로도 태깅하는 회사가 있지만 섞으면 합계가 무의미해진다.
        facts = (entry.get("units") or {}).get("USD") or []

        grouped: dict[int, list[dict[str, Any]]] = {}
        for fact in facts:
            if not _is_annual_report(fact.get("form") or ""):
                continue
            if duration and not _annual_duration(fact):
                continue
            if not duration and fact.get("start"):
                continue  # 시점 개념인데 기간이 붙어 있으면 우리가 찾는 잔액이 아니다
            year = fiscal_year_of(fact.get("end") or "")
            if year is None:
                continue
            grouped.setdefault(year, []).append(fact)

        for year, candidates in grouped.items():
            # 앞선 계정에서 이미 찾은 연도는 덮지 않는다. 우선순위가 앞선 계정이 이긴다.
            if year in by_year:
                continue
            picked = _pick_latest(candidates)
            if picked is not None:
                by_year[year] = picked

    return by_year


def extract_annual(facts: dict[str, Any]) -> list[YearFacts]:
    """companyfacts 응답에서 연도별 재무 요약을 만든다. 오래된 연도부터 돌려준다."""
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    if not us_gaap:
        return []

    per_metric: dict[str, dict[int, dict[str, Any]]] = {}
    for metric, concepts in DURATION_CONCEPTS.items():
        per_metric[metric] = _collect(us_gaap, concepts, duration=True)
    for metric, concepts in INSTANT_CONCEPTS.items():
        per_metric[metric] = _collect(us_gaap, concepts, duration=False)

    years = sorted({year for mapping in per_metric.values() for year in mapping})

    results: list[YearFacts] = []
    for year in years:
        values = {
            metric: (per_metric[metric].get(year) or {}).get("val") for metric in METRICS
        }
        if all(v is None for v in values.values()):
            continue

        # 출처는 그 해 사실들 중 가장 나중에 제출된 것을 대표로 삼는다.
        sources = [per_metric[m].get(year) for m in METRICS if per_metric[m].get(year)]
        newest = _pick_latest([s for s in sources if s]) or {}
        # 기간 종료일은 손익 쪽을 우선한다. 재무상태표 잔액일과 하루이틀 다를 수 있다.
        end_source = (
            per_metric["net_income"].get(year)
            or per_metric["revenue"].get(year)
            or newest
        )

        results.append(
            YearFacts(
                fiscal_year=year,
                period_end=end_source.get("end", ""),
                values=values,
                accession_no=newest.get("accn", ""),
                filed_date=newest.get("filed", ""),
            )
        )
    return results


def _save(cik: str, years: list[YearFacts]) -> int:
    if not years:
        return 0

    now = datetime.now(tz=None)
    rows = [
        {
            "cik": cik,
            "fiscal_year": y.fiscal_year,
            "period_end": y.period_end,
            **y.values,
            "currency": "USD",
            "accession_no": y.accession_no,
            "filed_date": y.filed_date,
        }
        for y in years
    ]
    del now  # fetched_at 은 모델 기본값이 채운다
    updatable = [c for c in rows[0] if c not in ("cik", "fiscal_year")]

    with get_session() as session:
        stmt = sqlite_insert(SecFinancial).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["cik", "fiscal_year"],
            set_={c: getattr(stmt.excluded, c) for c in updatable},
        )
        session.execute(stmt)
        session.commit()
    return len(rows)


def load(cik: str, years: int = 6) -> list[SecFinancial]:
    """저장된 연간 재무를 **오래된 연도부터** 돌려준다."""
    with get_session() as session:
        rows = list(
            session.execute(
                select(SecFinancial)
                .where(SecFinancial.cik == pad_cik(cik))
                .order_by(SecFinancial.fiscal_year.desc())
                .limit(years)
            ).scalars()
        )
    rows.reverse()
    return rows


def stored_count(cik: str) -> int:
    with get_session() as session:
        return session.execute(
            select(func.count()).select_from(SecFinancial).where(SecFinancial.cik == pad_cik(cik))
        ).scalar_one()


async def ensure_financials(cik: str, *, years: int = 6) -> int:
    """필요하면 SEC 에서 받아 저장한다. 저장한 행 수를 돌려준다.

    companyfacts 는 회사당 3~4MB 지만 전 연도가 한 번에 들어 있어 호출은 한 번이면 된다.
    이미 충분히 저장돼 있으면 부르지 않는다.
    """
    cik = pad_cik(cik)
    if stored_count(cik) >= years:
        return 0

    async with SecClient() as sec:
        facts = await sec.get_company_facts(cik)

    extracted = extract_annual(facts)
    if not extracted:
        logger.info("CIK %s: XBRL 에서 연간 재무를 찾지 못했다", cik)
        return 0

    # 파싱과 저장은 동기 작업이다. 이벤트 루프를 붙잡지 않게 스레드로 뺀다.
    return await asyncio.to_thread(_save, cik, extracted)
