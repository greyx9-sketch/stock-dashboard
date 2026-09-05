"""분기 재무를 뽑아 저장한다.

계정을 찾아내는 어려운 부분은 연간 쪽(`dart_financials`)이 이미 풀어 두었다 — 재무제표
구분(sj_div)을 먼저 보고, 업종마다 다른 계정 ID 를 우선순위로 훑고, 없으면 한글 계정명으로
찾는 그 로직을 그대로 가져다 쓴다. 여기서 새로 다루는 것은 **기간**뿐이다.

## 분기 보고서가 주는 금액 (실제 응답으로 확인, 2026-08-24)

손익계산서 줄 하나가 네 금액을 나란히 들고 온다:

| 필드 | 뜻 | 삼성전자 2025 반기 |
| --- | --- | --- |
| `thstrm_amount` | **당분기 3개월** | 74.57조 (2분기만) |
| `thstrm_add_amount` | 연초부터 누적 | 153.71조 (상반기) |
| `frmtrm_q_amount` | 전년 동분기 3개월 | 74.07조 |
| `frmtrm_add_amount` | 전년 같은 시점까지 누적 | 145.98조 |

검산도 맞는다 — 1분기 79.14조 + 2분기 74.57조 = 153.71조.

재무상태표는 다르다. `thstrm_amount` 가 **분기말 잔액**이고 누적 칸이 아예 없다. 잔액에
"3개월치"라는 개념이 없기 때문이다.

## 전년 칸을 쓰지 않는 이유

`frmtrm_q_amount` 를 쓰면 호출 수를 절반으로 줄일 수 있다. 그런데 그 줄에는 **재무상태표가
없다** — 재무상태표의 `frmtrm_amount` 는 전년 동분기가 아니라 **전기말**(직전 연말)이다.
전년 분기 행을 손익만 채워 넣으면 그 행의 접수번호가 '이번' 보고서 것이 되고, 나중에
진짜 그 분기 보고서를 받아 와도 접수번호가 더 **옛날**이라 덮어쓰지 못한다(아래 `_save`
참고). 재무상태표가 영영 비는 것이다.

그래서 **해마다 그 해 보고서를 직접 부른다.** 호출이 늘지만 한 번만 받아 오면 되고,
행이 반쪽으로 남는 함정이 없다.

## 4분기가 없는 이유

DART 에 4분기 보고서라는 것이 없다. 사업보고서가 그 자리를 대신하므로 4분기 손익은
`연간 − 3분기 누적`으로만 구한다. 계산값이라 저장하지 않고 조회할 때 만든다
(`routers/financials.py`).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.clients.dart import HALF_REPORT, Q1_REPORT, Q3_REPORT, DartClient
from app.clock import today_kst
from app.models.base import get_session
from app.models.quarterly import DartQuarterly
from app.services.dart_financials import _find_row, _to_int

logger = logging.getLogger(__name__)

# 분기 번호 → 보고서 종류. 2분기는 '반기보고서'가 담당한다(2분기 전용 보고서는 없다).
QUARTER_REPORT = {1: Q1_REPORT, 2: HALF_REPORT, 3: Q3_REPORT}

INCOME_METRICS = ("revenue", "gross_profit", "operating_income", "net_income")
BALANCE_METRICS = ("total_assets", "total_liabilities", "total_equity")

# 분기보고서 제출 기한(분기 종료 후 45일). 12월 결산 회사 기준으로 대략 이 날짜 뒤에
# 나온다. 아직 나오지 않았을 게 뻔한 분기를 부르지 않으려는 것뿐이라 정확할 필요는 없다.
#
# **12월 결산이 아닌 회사에는 맞지 않는다.** 그런 회사는 최근 분기를 한 번 늦게 받아 올 수
# 있다(빈 응답이 오고, 다음에 다시 부르면 들어온다). 틀린 값을 만들지는 않는다.
FILED_AFTER = {1: (5, 20), 2: (8, 20), 3: (11, 20)}


@dataclass(frozen=True)
class QuarterFinancial:
    """한 분기의 재무 요약. DB 에 넣기 전 중간 형태."""

    fiscal_year: int
    quarter: int
    values: dict[str, int | None]
    currency: str
    receipt_no: str


def due_quarters(today: date | None = None, *, years: int = 3) -> list[tuple[int, int]]:
    """지금 시점에 보고서가 나와 있을 만한 (연도, 분기) 목록. **최근 것부터.**

    아직 제출 기한이 지나지 않은 분기는 넣지 않는다 — 부르면 빈 응답이 오므로 호출만
    버린다. 기한이 지났는데 아직 안 낸 회사는 빈 응답이 오고, 다음에 다시 부르면 들어온다.
    """
    today = today or today_kst()
    out: list[tuple[int, int]] = []
    for year in range(today.year, today.year - years, -1):
        for quarter in (3, 2, 1):
            month, day = FILED_AFTER[quarter]
            if (year, month, day) <= (today.year, today.month, today.day):
                out.append((year, quarter))
    return out


def extract_quarter(
    rows: list[dict[str, str]], *, year: int, quarter: int
) -> QuarterFinancial | None:
    """분기 응답 하나에서 그 분기 한 행을 뽑는다. 쓸 값이 하나도 없으면 None.

    손익은 3개월치와 누적을 **둘 다** 담는다. 둘 다 보고서에 적힌 원값이다.
    """
    if not rows:
        return None

    values: dict[str, int | None] = {}

    for metric in INCOME_METRICS:
        row = _find_row(rows, metric)
        if row is None:
            values[metric] = None
            values[f"{metric}_cum"] = None
            continue
        qtr = _to_int(row.get("thstrm_amount"))
        cum = _to_int(row.get("thstrm_add_amount"))
        # 1분기는 누적과 당분기가 같은 기간이다. 누적 칸을 비워 보내는 회사가 있어도
        # 이건 계산이 아니라 정의상 같은 값이라 그대로 채운다.
        if cum is None and quarter == 1:
            cum = qtr
        values[metric] = qtr
        values[f"{metric}_cum"] = cum

    for metric in BALANCE_METRICS:
        row = _find_row(rows, metric)
        # 재무상태표는 분기말 잔액 하나뿐이다. 누적 칸이 없다.
        values[metric] = _to_int(row.get("thstrm_amount")) if row is not None else None

    if all(v is None for v in values.values()):
        return None

    return QuarterFinancial(
        fiscal_year=year,
        quarter=quarter,
        values=values,
        currency=(rows[0].get("currency") or "KRW").strip() or "KRW",
        receipt_no=(rows[0].get("rcept_no") or "").strip(),
    )


def _save(corp_code: str, fs_div: str, quarters: list[QuarterFinancial]) -> int:
    if not quarters:
        return 0

    rows = [
        {
            "corp_code": corp_code,
            "fiscal_year": q.fiscal_year,
            "quarter": q.quarter,
            "fs_div": fs_div,
            **q.values,
            "currency": q.currency,
            "receipt_no": q.receipt_no,
        }
        for q in quarters
    ]
    keys = ("corp_code", "fiscal_year", "quarter", "fs_div")
    updatable = [c for c in rows[0] if c not in keys]

    with get_session() as session:
        stmt = sqlite_insert(DartQuarterly).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(keys),
            set_={c: getattr(stmt.excluded, c) for c in updatable},
            # 같은 분기가 정정보고서로 다시 올 수 있다. 항상 **더 나중에 제출된** 것을
            # 남긴다. 접수번호가 YYYYMMDD###### 라 문자열 비교가 곧 제출 시점 비교다.
            where=sqlite_insert(DartQuarterly).excluded.receipt_no > DartQuarterly.receipt_no,
        )
        session.execute(stmt)
        session.commit()
    return len(rows)


def stored_quarters(corp_code: str, fs_div: str) -> set[tuple[int, int]]:
    with get_session() as session:
        return set(
            session.execute(
                select(DartQuarterly.fiscal_year, DartQuarterly.quarter)
                .where(DartQuarterly.corp_code == corp_code)
                .where(DartQuarterly.fs_div == fs_div)
            ).all()
        )


def load(corp_code: str, fs_div: str, limit: int = 12) -> list[DartQuarterly]:
    """저장된 분기를 **오래된 것부터** 돌려준다. 차트가 그대로 그릴 수 있는 순서다."""
    with get_session() as session:
        rows = list(
            session.execute(
                select(DartQuarterly)
                .where(DartQuarterly.corp_code == corp_code)
                .where(DartQuarterly.fs_div == fs_div)
                .order_by(DartQuarterly.fiscal_year.desc(), DartQuarterly.quarter.desc())
                .limit(limit)
            ).scalars()
        )
    rows.reverse()
    return rows


async def ensure_quarterly(
    corp_code: str, *, years: int = 3, consolidated: bool = True
) -> tuple[str, int]:
    """필요한 분기를 채운다. (실제 사용한 fs_div, 저장한 행 수) 를 돌려준다.

    분기 보고서 하나가 분기 하나만 담으므로 **분기마다 한 번씩** 부른다. 이미 저장된
    분기는 건너뛰므로 처음 한 번만 오래 걸리고 그 뒤로는 새 분기 하나씩만 늘어난다.

    연결(CFS)이 없는 회사는 별도(OFS)로 자동 전환한다. 종속회사가 없으면 연결재무제표를
    작성하지 않기 때문이다.
    """
    fs_div = "CFS" if consolidated else "OFS"
    have = stored_quarters(corp_code, fs_div)
    # 연결/별도 중 어느 쪽을 쓰는 회사인지 아직 모르는 상태. 처음 값을 받아 낸 순간 정해진다.
    fs_confirmed = bool(have)
    saved = 0

    async with DartClient() as dart:
        for year, quarter in due_quarters(years=years):
            if (year, quarter) in have:
                continue

            rows = await dart.get_financial_statements(
                corp_code,
                year=year,
                report_code=QUARTER_REPORT[quarter],
                consolidated=(fs_div == "CFS"),
            )

            # 아직 연결/별도를 확정하지 못한 채 빈 응답이면 반대쪽을 한 번 시험한다.
            # 빈 응답이 "그 분기 보고서가 없다"인지 "이 회사는 연결을 안 낸다"인지
            # 구분할 방법이 이것뿐이다.
            if not rows and not fs_confirmed:
                other = "OFS" if fs_div == "CFS" else "CFS"
                rows = await dart.get_financial_statements(
                    corp_code,
                    year=year,
                    report_code=QUARTER_REPORT[quarter],
                    consolidated=(other == "CFS"),
                )
                if rows:
                    logger.info("%s: 분기 재무를 %s 로 조회한다", corp_code, other)
                    fs_div = other
                    have = stored_quarters(corp_code, fs_div)

            if not rows:
                continue

            fs_confirmed = True
            extracted = extract_quarter(rows, year=year, quarter=quarter)
            if extracted is None:
                continue

            # 동기 DB 쓰기다. 이벤트 루프를 붙잡지 않게 스레드로 뺀다.
            saved += await asyncio.to_thread(_save, corp_code, fs_div, [extracted])
            have.add((year, quarter))

    return fs_div, saved
