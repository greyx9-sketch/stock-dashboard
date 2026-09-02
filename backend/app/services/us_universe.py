"""미국 동종업계 비교가 볼 유니버스를 채운다.

국내(`universe.py`)와 하는 일이 같다. 다른 점 둘:

**1. 업종을 SIC 로 묶는다.** SEC 가 제출 정보(`submissions`)에 네 자리 SIC 코드와
이름을 함께 준다 — `3674 Semiconductors & Related Devices`. 국내 DART 코드는 자릿수가
회사마다 달라 앞 두 자리로 잘라야 했지만, SIC 는 길이가 일정해서 **그대로 맞춰 묶는다.**
이름이 있어 화면에 "같은 업종"이 무엇인지 적을 수도 있다.

**2. 유니버스가 훨씬 작다.** 국내는 KRX 확정 시세를 매일 통째로 받아 두므로 시가총액
상위 300종목을 공짜로 고를 수 있다. 미국은 그런 자료가 없고, 회사 하나의 재무를 받으려면
3~4MB 짜리 응답을 받아야 한다. 그래서 **토스 거래대금 상위**에서 100종목만 담는다 —
사용자가 실제로 화면에서 보는 종목들이다.

그래서 동종업계에 나오는 종목도 그 100개 안에서만 나온다. 화면에 그 사실을 밝힌다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.clients.sec import SecClient, SecError
from app.models.base import get_session
from app.models.us_company import SecCompany, SecFinancial
from app.services import sec_companies, sec_financials

logger = logging.getLogger(__name__)

# 담을 종목 수. 위 "2. 유니버스가 훨씬 작다" 참고.
DEFAULT_SIZE = 100

MAX_CONSECUTIVE_FAILURES = 10


@dataclass
class UsLoadReport:
    started_at: datetime
    finished_at: datetime | None = None
    requested: int = 0
    financials_saved: int = 0
    industries_saved: int = 0
    skipped_unknown: int = 0
    failed: list[str] = field(default_factory=list)


def _store_sic(cik: str, sic: str | None, description: str | None) -> bool:
    if not sic:
        return False
    with get_session() as session:
        result = session.execute(
            update(SecCompany)
            .where(SecCompany.cik == cik)
            .where(SecCompany.sic.is_(None))
            .values(sic=str(sic), sic_description=(description or "").strip() or None)
        )
        session.commit()
        return result.rowcount > 0


def remember_industry(cik: str, submissions: dict) -> None:
    """제출 정보에서 업종을 챙겨 둔다. **이미 알고 있으면 아무 일도 하지 않는다.**

    유니버스 적재가 훑지 않는 종목도 사용자가 열면 여기로 들어온다 — 공시 목록을
    보려면 어차피 같은 응답을 받아야 하므로 새 호출이 없다.
    """
    try:
        _store_sic(cik, submissions.get("sic"), submissions.get("sicDescription"))
    except Exception:  # 곁다리다. 실패해도 공시 목록은 그대로 나와야 한다.
        logger.warning("업종을 저장하지 못했다 — CIK %s", cik, exc_info=True)


def industry_of(ticker: str) -> tuple[str | None, str | None]:
    """(SIC 코드, 업종 이름). 아직 모르면 (None, None)."""
    company = sec_companies.get_company(ticker)
    if company is None:
        return None, None
    return company.sic, company.sic_description


def peers(ticker: str, limit: int = 12) -> list[str]:
    """같은 SIC 의 다른 종목. **재무를 이미 받아 둔 종목만** 나온다.

    업종을 모르면 빈 목록이다 — 아무 종목이나 '동종업계'라고 보여주느니 비워 둔다.
    """
    sic, _ = industry_of(ticker)
    if not sic:
        return []

    with get_session() as session:
        rows = session.execute(
            select(SecCompany.ticker)
            .where(SecCompany.sic == sic)
            .where(SecCompany.ticker != ticker)
            # 시가총액을 알아야 정렬이 되는데 그건 주가가 있어야 한다. 여기서는 발행
            # 주식수만 보고 거른다 — 그것조차 없으면 지표를 하나도 못 낸다.
            .where(SecCompany.shares_outstanding.isnot(None))
            .order_by(SecCompany.shares_outstanding.desc())
            .limit(limit)
        ).scalars()
        return list(rows)


# 상품신탁·ETF 의 SIC. 이 코드로 들어오는 것은 회사가 아니다 — 금 ETF(GLD·IAU),
# 원유 ETF(USO), ProShares 레버리지 상품 따위다. 주당순이익이라는 것이 없으므로
# PER 을 매기면 뜻 없는 숫자가 나온다.
FUND_SIC = frozenset({"6221"})


def screen_universe() -> list[str]:
    """스크리너가 훑을 미국 종목. **한 회사에 한 줄만 나온다.**

    두 가지를 거른다.

    **1. 회사가 아닌 것.** SIC 6221 은 상품신탁·ETF 다(위 `FUND_SIC` 참고).

    **2. 같은 회사의 다른 종이.** 미국은 우선주(`JPM-PC`)·워런트(`DAICW`)·ETN 이
    본주와 **같은 CIK 를 쓴다.** SEC 재무는 CIK 단위라 그대로 두면 한 회사의 재무가
    티커 수만큼 복제된다. 실제로 ProShares Trust II 하나가 티커 16개로, JPMorgan 이
    9개로 들어와 있었다 — 74개처럼 보이던 것이 정리하면 38개다.

    대표 티커는 **가장 짧은 것**을 고른다. 우선주·워런트는 본주 티커에 글자를 덧붙여
    만들므로(JPM → JPM-PC, DAIC → DAICW) 짧은 쪽이 본주다. 길이가 같으면 사전순으로
    끊는다 — 드물고, 어느 쪽이든 같은 회사의 같은 재무를 가리킨다.

    재무와 발행주식수가 둘 다 있어야 넣는다. 하나라도 없으면 지표를 한 줄도 못 낸다.
    """
    with get_session() as session:
        rows = session.execute(
            select(SecCompany.cik, SecCompany.ticker)
            .where(SecCompany.shares_outstanding.isnot(None))
            .where(SecCompany.shares_outstanding > 0)
            .where(
                SecCompany.sic.is_(None) | SecCompany.sic.notin_(FUND_SIC)
            )
            .where(
                select(SecFinancial.cik)
                .where(SecFinancial.cik == SecCompany.cik)
                .exists()
            )
        ).all()

    best: dict[str, str] = {}
    for cik, ticker in rows:
        current = best.get(cik)
        if current is None or (len(ticker), ticker) < (len(current), current):
            best[cik] = ticker
    return sorted(best.values())


async def load(tickers: list[str]) -> UsLoadReport:
    """이 종목들의 재무·발행주식수·업종을 채운다. 이미 받아 둔 것은 건너뛴다.

    한 종목이 실패해도 멈추지 않는다 — ETF·DR 처럼 10-K 를 내지 않는 종목이 목록에
    늘 섞여 있다. 다만 연달아 열 번 실패하면 멈춘다.
    """
    report = UsLoadReport(started_at=datetime.now(timezone.utc), requested=len(tickers))
    consecutive = 0

    for ticker in tickers:
        company = sec_companies.get_company(ticker)
        if company is None:
            # SEC 목록에 없는 종목(일부 DR·ETF). 오류가 아니다.
            report.skipped_unknown += 1
            continue

        try:
            report.financials_saved += await sec_financials.ensure_financials(
                company.cik, years=4
            )

            if company.sic is None:
                async with SecClient() as sec:
                    submissions = await sec.get_submissions(company.cik)
                if _store_sic(
                    company.cik, submissions.get("sic"), submissions.get("sicDescription")
                ):
                    report.industries_saved += 1

            consecutive = 0
        except (SecError, RuntimeError) as exc:
            report.failed.append(f"{ticker}: {type(exc).__name__}")
            consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                logger.error("미국 유니버스 적재를 멈춘다 — %d회 연속 실패", consecutive)
                break
        except asyncio.CancelledError:
            raise

    report.finished_at = datetime.now(timezone.utc)
    logger.info(
        "미국 유니버스 적재 완료 — 종목 %d · 재무 %d행 · 업종 %d건 · 건너뜀 %d · 실패 %d",
        report.requested,
        report.financials_saved,
        report.industries_saved,
        report.skipped_unknown,
        len(report.failed),
    )
    return report
