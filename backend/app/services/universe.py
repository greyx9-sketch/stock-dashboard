"""스크리너·동종업계 비교가 볼 **유니버스**를 미리 채워 둔다.

## 왜 미리 받아 두는가

지금까지는 종목 하나를 열 때 그 종목의 재무를 받아 왔다. 화면 하나에 몇 초면 되는
방식이지만, 스크리너는 다르다 — "PER 15배 이하"를 고르려면 **모든 후보의 PER 을 이미
알고 있어야** 한다. 조회 시점에 300종목을 받아 오면 몇 분이 걸린다.

그래서 시가총액 상위 종목의 재무·배당·업종을 하룻밤에 한 번 받아 DB 에 넣어 둔다.
스크리너는 DB 만 읽는다.

## 왜 '주요계정' 일괄 조회를 쓰지 않는가

DART 에 여러 회사를 한 번에 부르는 API 가 있다(`fnlttMultiAcnt`). 훨씬 빠르지만
**지배주주 몫을 주지 않는다** — 당기순이익·자본총계만 준다.

이 프로젝트의 PER·PBR 은 지배주주 몫으로 낸다(`services/valuation.py` 참고). 스크리너만
다른 자료로 계산하면 **같은 종목의 PER 이 목록과 상세에서 다르게 보인다.** 그런 화면은
어느 쪽을 믿어야 할지 알 수 없어 못 쓴다. 느리더라도 같은 길로 받는다.

전체 재무제표는 회사당 1~2번 호출이면 3개 연도를 덮는다. 300종목이면 수백 건인데,
DART 하루 한도가 2만 건이라 여유롭다.

## 얼마나 담는가

시가총액 상위 **300종목**이 기본값이다. 코스피·코스닥을 합쳐 이 정도면 사람이 실제로
후보에 올릴 종목은 거의 들어온다. 더 늘리는 것은 호출 수만 늘리고 값어치가 빠르게
줄어든다 — 시총 하위 종목은 재무가 부실해 스크리너 조건에 어차피 걸리지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.clients.dart import DartClient, DartError
from app.models.base import get_session
from app.models.corp import DartCorp
from app.models.quote import KrxDailyQuote
from app.services import dart_financials, dart_corps
from app.services import dividends as dividends_service

logger = logging.getLogger(__name__)

# 유니버스 크기. 위 "얼마나 담는가" 참고.
DEFAULT_SIZE = 300

# 한 종목을 처리하다 실패해도 나머지를 계속한다. 이만큼 연달아 실패하면 멈춘다 —
# 키가 막혔거나 DART 가 죽은 상황이라 계속 두드려 봐야 소용없다.
MAX_CONSECUTIVE_FAILURES = 10


@dataclass
class LoadReport:
    """적재 결과. 화면과 로그가 같은 근거를 쓰도록 수치를 그대로 담는다."""

    started_at: datetime
    finished_at: datetime | None = None
    requested: int = 0
    financials_saved: int = 0
    dividends_saved: int = 0
    industries_saved: int = 0
    skipped_no_corp: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.finished_at is not None and len(self.failed) < MAX_CONSECUTIVE_FAILURES


def top_symbols(size: int = DEFAULT_SIZE) -> list[str]:
    """시가총액 상위 종목. **가장 최근 거래일 기준**이다.

    KRX 확정 시세 표에서 고른다 — 우리가 이미 매일 받아 두는 자료라 새 호출이 없다.
    """
    with get_session() as session:
        latest = session.execute(
            select(KrxDailyQuote.trade_date).order_by(KrxDailyQuote.trade_date.desc()).limit(1)
        ).scalar()
        if latest is None:
            return []
        return list(
            session.execute(
                select(KrxDailyQuote.symbol)
                .where(KrxDailyQuote.trade_date == latest)
                .order_by(KrxDailyQuote.market_cap.desc())
                .limit(size)
            ).scalars()
        )


def _store_industry(corp_code: str, induty_code: str | None) -> bool:
    if not induty_code:
        return False
    with get_session() as session:
        result = session.execute(
            update(DartCorp)
            .where(DartCorp.corp_code == corp_code)
            .where(DartCorp.induty_code.is_(None))
            .values(induty_code=induty_code)
        )
        session.commit()
        return result.rowcount > 0


# 업종을 묶는 자릿수. 표준산업분류는 앞에서부터 대→중→소→세분류로 좁혀지는데,
# **앞 2자리(중분류)** 가 사람이 말하는 "업종"에 가장 가깝다.
#
# 정확히 일치시키면 안 되는 이유: **DART 가 주는 코드의 자릿수가 회사마다 다르다.**
# 삼성전자는 `264`, SK하이닉스는 `2612` 다. 같은 전자부품인데 완전 일치로는 영영
# 안 묶인다. 앞 2자리로 자르면 둘 다 `26` 이 된다.
INDUSTRY_PREFIX = 2

# 지주회사 분류. 표준산업분류가 **사업 내용이 아니라 법적 형태**로 묶는 자리라,
# 금융지주(KB금융·신한지주)와 일반 지주(SK·HD한국조선해양)가 같은 코드다.
# 지우지 않고 화면에 그 사정을 밝힌다 — 비워 두는 것보다는 낫고, 설명이 있으면
# 사람이 걸러 읽을 수 있다.
HOLDING_COMPANY_PREFIX = "649"


def industry_of(stock_code: str) -> str | None:
    """그 종목의 표준산업분류 코드(원본 그대로)."""
    corp = dart_corps.get_corp(stock_code)
    return corp.induty_code if corp else None


def industry_group(stock_code: str) -> str | None:
    """동종업계를 묶는 기준 코드(앞 2자리). 업종을 모르면 None."""
    code = industry_of(stock_code)
    return code[:INDUSTRY_PREFIX] if code else None


def is_holding_company(stock_code: str) -> bool:
    """지주회사로 분류돼 있는가. 화면이 그 사정을 밝힐지 판단하는 데 쓴다."""
    code = industry_of(stock_code)
    return bool(code and code.startswith(HOLDING_COMPANY_PREFIX))


def peers(stock_code: str, limit: int = 12) -> list[str]:
    """같은 업종의 다른 종목. **시가총액 큰 순으로** 돌려준다.

    업종을 모르는 종목은 빈 목록이다 — 아무 종목이나 '동종업계'라고 보여주느니
    비워 둔다.
    """
    group = industry_group(stock_code)
    if not group:
        return []

    with get_session() as session:
        latest = session.execute(
            select(KrxDailyQuote.trade_date).order_by(KrxDailyQuote.trade_date.desc()).limit(1)
        ).scalar()
        if latest is None:
            return []
        rows = session.execute(
            select(KrxDailyQuote.symbol)
            .join(DartCorp, DartCorp.stock_code == KrxDailyQuote.symbol)
            .where(KrxDailyQuote.trade_date == latest)
            .where(DartCorp.induty_code.like(f"{group}%"))
            .order_by(KrxDailyQuote.market_cap.desc())
            .limit(limit + 1)
        ).scalars()
    return [s for s in rows if s != stock_code][:limit]


async def load(size: int = DEFAULT_SIZE) -> LoadReport:
    """유니버스를 채운다. **이미 받아 둔 것은 건너뛰므로** 두 번째부터는 빠르다.

    한 종목이 실패해도 멈추지 않는다 — 상장폐지 직전이라 보고서가 없거나, DART 에
    자료가 빠진 회사가 늘 몇 개씩 있다. 다만 연달아 열 번 실패하면 멈춘다.
    """
    report = LoadReport(started_at=datetime.now(timezone.utc))
    symbols = top_symbols(size)
    report.requested = len(symbols)
    consecutive = 0

    latest_year = dart_financials.latest_annual_year()

    for symbol in symbols:
        corp = dart_corps.get_corp(symbol)
        if corp is None:
            # 우선주·리츠 등 DART 매핑이 없는 종목. 오류가 아니다.
            report.skipped_no_corp += 1
            continue

        try:
            _, saved = await dart_financials.ensure_financials(corp.corp_code, years=3)
            report.financials_saved += saved
            report.dividends_saved += await dividends_service.ensure_dividends(
                corp.corp_code, [latest_year, latest_year - 1]
            )

            if corp.induty_code is None:
                async with DartClient() as dart:
                    company = await dart.get_company(corp.corp_code)
                if company and _store_industry(corp.corp_code, company.get("induty_code")):
                    report.industries_saved += 1

            consecutive = 0
        except (DartError, RuntimeError) as exc:
            report.failed.append(f"{symbol}: {type(exc).__name__}")
            consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                logger.error("유니버스 적재를 멈춘다 — %d회 연속 실패", consecutive)
                break
        except asyncio.CancelledError:
            raise

    report.finished_at = datetime.now(timezone.utc)
    logger.info(
        "유니버스 적재 완료 — 종목 %d · 재무 %d행 · 배당 %d건 · 업종 %d건 · 실패 %d",
        report.requested,
        report.financials_saved,
        report.dividends_saved,
        report.industries_saved,
        len(report.failed),
    )
    return report
