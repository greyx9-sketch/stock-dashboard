"""새 연차보고서가 올라오면 알아서 분석한다. 기획서 6.2.

지금까지는 사람이 종목을 열고 **"분석하기"를 눌러야** 했다. 연차보고서는 1년에 한 번
나오므로, 새 보고서가 올라온 것을 알아채는 일 자체가 사람 몫이었다.

## 감지는 이미 되어 있었다

`tenk_analysis.analyze()` 와 `dart_analysis.analyze()` 는 **최신 보고서를 찾아보고 이미
분석했으면 API 를 부르지 않는다.** 즉 "새 보고서인가"를 가리는 일이 그 안에 이미 있다.
여기서 새로 만드는 것은 **언제 훑을 것인가**와 **얼마까지 쓸 것인가**뿐이다.

## 관심종목만 훑는다

기획서가 "관심 유니버스에 속한 CIK" 라고 적어 둔 그대로다. 유니버스(국내 300 · 미국
100)를 전부 훑으면 새 보고서가 몰리는 3월에 수십 건이 한꺼번에 돌아 **돈이 크게 나간다.**
관심종목은 사용자가 직접 담은 것이라 분석할 값어치가 확실하고, 수가 적다(최대 60).

## 사용자 몫을 남긴다 — 이 파일에서 가장 중요한 규칙

분석은 **돈이 나가는 유일한 경로**다(문서 한 건 200~340원). 하루 상한이 `.env` 의
`ANALYSIS_DAILY_LIMIT` 로 걸려 있는데, 자동 분석이 그것을 다 써 버리면 **사람이
누르려던 분석이 막힌다.** 자기가 시키지도 않은 일 때문에 막히는 것이라 나쁘다.

그래서 둘을 건다:

- **한 번에 최대 3건.** 3월처럼 여러 회사가 한꺼번에 보고서를 내도 며칠에 걸쳐 나눠 한다.
- **항상 5건을 남긴다.** 오늘 쓴 건수가 (상한 − 5)에 닿으면 자동 분석은 멈춘다.

연차보고서는 회사당 1년에 한 번이라 평소에는 아무 일도 하지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from app.config import get_settings
from app.models.base import get_session
from app.models.watchlist import WatchlistItem
from app.services import dart_analysis, dart_corps, llm_budget, sec_companies, tenk_analysis

logger = logging.getLogger(__name__)

# 한 번 돌 때 자동으로 분석할 최대 건수.
MAX_PER_RUN = 3

# 사람이 직접 누를 몫으로 늘 남겨 두는 건수.
MANUAL_RESERVE = 5


@dataclass
class AutoReport:
    """무엇을 했는지. 로그와 나중의 점검이 같은 근거를 쓰도록 수치를 담는다."""

    checked: int = 0
    analyzed: list[str] = field(default_factory=list)
    already_had: int = 0
    skipped_no_report: list[str] = field(default_factory=list)
    stopped_reason: str | None = None
    failed: list[str] = field(default_factory=list)


def _watchlist_symbols() -> list[str]:
    with get_session() as session:
        return list(
            session.execute(
                select(WatchlistItem.symbol).order_by(
                    WatchlistItem.sort_order, WatchlistItem.symbol
                )
            ).scalars()
        )


def budget_left() -> int:
    """자동 분석이 지금 더 써도 되는 건수. 0 이면 오늘은 그만둔다."""
    limit = get_settings().analysis_daily_limit
    allowed = max(limit - MANUAL_RESERVE, 0)
    return max(allowed - llm_budget.calls_today(), 0)


async def _analyze_one(symbol: str) -> tuple[str, str]:
    """한 종목. (결과, 설명) 을 돌려준다.

    결과는 `analyzed` · `already` · `no-report` 중 하나다. 이미 분석돼 있으면 API 를
    부르지 않으므로 돈이 들지 않는다 — 그 판단은 각 `analyze()` 안에 있다.
    """
    if symbol.isdigit() and len(symbol) == 6:
        corp = dart_corps.get_corp(symbol)
        if corp is None:
            return "no-report", "DART 고유번호 없음"
        before = dart_analysis.load(symbol)
        row = await dart_analysis.analyze(corp)
        fresh = before is None or before.receipt_no != row.receipt_no
        return ("analyzed" if fresh else "already"), row.receipt_no

    company = sec_companies.get_company(symbol)
    if company is None:
        return "no-report", "SEC 목록에 없음"
    before = tenk_analysis.load(symbol)
    row = await tenk_analysis.analyze(company)
    fresh = before is None or before.accession_no != row.accession_no
    return ("analyzed" if fresh else "already"), row.accession_no


async def run() -> AutoReport:
    """관심종목에 새 연차보고서가 있으면 분석한다.

    **한 종목이 실패해도 멈추지 않는다** — 상장폐지·ETF·보고서 미제출처럼 분석할 문서가
    없는 종목이 섞여 있다. 다만 예산이 바닥나면 그 자리에서 멈춘다.
    """
    report = AutoReport()
    symbols = _watchlist_symbols()

    for symbol in symbols:
        if len(report.analyzed) >= MAX_PER_RUN:
            report.stopped_reason = f"한 번에 {MAX_PER_RUN}건까지만 합니다."
            break
        if budget_left() <= 0:
            report.stopped_reason = f"사람이 쓸 몫({MANUAL_RESERVE}건)을 남겨 두고 멈췄습니다."
            break

        report.checked += 1
        try:
            outcome, detail = await _analyze_one(symbol)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 분석 실패는 흔하다(원문 형식·모델 응답). 나머지 종목은 계속 본다.
            report.failed.append(f"{symbol}: {type(exc).__name__}")
            continue

        if outcome == "analyzed":
            report.analyzed.append(symbol)
            logger.info("자동 분석 — %s 의 새 보고서를 분석했다 (%s)", symbol, detail)
        elif outcome == "already":
            report.already_had += 1
        else:
            report.skipped_no_report.append(symbol)

    logger.info(
        "자동 분석 완료 — 확인 %d · 새로 분석 %d · 이미 있음 %d · 문서 없음 %d · 실패 %d%s",
        report.checked,
        len(report.analyzed),
        report.already_had,
        len(report.skipped_no_report),
        len(report.failed),
        f" · {report.stopped_reason}" if report.stopped_reason else "",
    )
    return report
