"""XBRL 재무제표에서 연도별 핵심 수치를 뽑아 저장한다.

**모든 숫자는 XBRL 계정에서 직접 가져온다.** LLM 에게 문서를 읽혀 숫자를 뽑게 하지 않는다
(CLAUDE.md 절대 규칙 3). 마진·성장률도 여기서 저장하지 않고, 조회 시점에 원값으로 계산한다.

여러 업종의 실제 응답을 확인하면서 발견한 함정 세 가지를 이 파일이 처리한다.

1. **재무제표 구분(sj_div)을 반드시 봐야 한다.** 자본변동표(SCE)에는 `ifrs-full_Equity` 나
   `ifrs-full_ProfitLoss` 가 구성요소별로 수십 줄씩 들어 있다. 삼성전자 2025 응답에서
   `ifrs-full_Equity` 는 SCE 에만 7줄이 있었다. 구분 없이 첫 줄을 집으면 자본총계 대신
   자본 구성항목 하나를 집게 된다.

2. **손익 항목이 IS 에 있을 수도 CIS 에 있을 수도 있다.** 삼성전자·기아·셀트리온은
   손익계산서(IS)를 따로 내지만, 카카오·KB금융은 포괄손익계산서(CIS) 하나만 낸다.

3. **계정 ID 가 업종마다 다르고, 아예 없는 항목도 있다.** 영업이익은 대부분
   `dart_OperatingIncomeLoss` 지만 KB금융은 `ifrs-full_ProfitLossFromOperatingActivities`
   를 쓴다. KB금융에는 `ifrs-full_Revenue` 가 아예 없다 — 금융지주는 매출액 개념을 쓰지
   않기 때문이다. 그래서 모든 항목이 없을 수 있다고 보고 None 을 허용한다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.clients.dart import ANNUAL_REPORT, DartClient
from app.models.base import get_session
from app.models.financial import DartFinancial

logger = logging.getLogger(__name__)

# 손익 항목은 손익계산서에, 재무상태 항목은 재무상태표에만 있다.
# 자본변동표(SCE)·현금흐름표(CF)는 같은 계정 ID 를 다른 뜻으로 쓰므로 절대 보지 않는다.
INCOME_SECTIONS = ("IS", "CIS")
BALANCE_SECTIONS = ("BS",)

# 항목별로 찾아볼 계정 ID 를 우선순위대로 둔다. 앞에서 찾으면 뒤는 보지 않는다.
ACCOUNT_IDS: dict[str, tuple[str, ...]] = {
    "revenue": ("ifrs-full_Revenue", "ifrs-full_RevenueFromContractsWithCustomers"),
    "gross_profit": ("ifrs-full_GrossProfit",),
    "operating_income": (
        "dart_OperatingIncomeLoss",
        "ifrs-full_ProfitLossFromOperatingActivities",
    ),
    "net_income": ("ifrs-full_ProfitLoss",),
    "total_assets": ("ifrs-full_Assets",),
    "total_liabilities": ("ifrs-full_Liabilities",),
    "total_equity": ("ifrs-full_Equity",),
}

# 계정 ID 로 못 찾았을 때 쓸 한글 계정명. 표준 ID 를 안 쓰는 회사가 드물게 있다.
ACCOUNT_NAMES: dict[str, tuple[str, ...]] = {
    "revenue": ("매출액", "영업수익", "수익(매출액)", "매출"),
    "gross_profit": ("매출총이익",),
    "operating_income": ("영업이익", "영업이익(손실)"),
    "net_income": ("당기순이익", "당기순이익(손실)", "당기순손익"),
    "total_assets": ("자산총계",),
    "total_liabilities": ("부채총계",),
    "total_equity": ("자본총계",),
}

WHICH_SECTIONS: dict[str, tuple[str, ...]] = {
    "revenue": INCOME_SECTIONS,
    "gross_profit": INCOME_SECTIONS,
    "operating_income": INCOME_SECTIONS,
    "net_income": INCOME_SECTIONS,
    "total_assets": BALANCE_SECTIONS,
    "total_liabilities": BALANCE_SECTIONS,
    "total_equity": BALANCE_SECTIONS,
}

# 한 응답이 담고 있는 세 개 연도. (금액 필드, 당기 대비 몇 년 전인가)
PERIOD_FIELDS = (("thstrm_amount", 0), ("frmtrm_amount", 1), ("bfefrmtrm_amount", 2))

METRICS = tuple(ACCOUNT_IDS)


@dataclass(frozen=True)
class YearlyFinancial:
    """한 회계연도의 재무 요약. DB 에 넣기 전 중간 형태."""

    fiscal_year: int
    values: dict[str, int | None]
    currency: str
    receipt_no: str


def _to_int(raw: str | None) -> int | None:
    """DART 금액 문자열을 정수로. 빈 값·'-' 는 없는 값으로 다룬다.

    금액에 콤마가 섞여 오는 경우가 있어 먼저 걷어낸다. 괄호 표기(1,234)는 음수다.
    """
    if raw is None:
        return None
    text = raw.strip().replace(",", "").replace(" ", "")
    if text in ("", "-", "－"):
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        value = int(text)
    except ValueError:
        return None
    return -value if negative else value


def _find_row(rows: list[dict[str, str]], metric: str) -> dict[str, str] | None:
    """한 항목에 해당하는 계정 줄을 찾는다.

    반드시 재무제표 구분으로 먼저 좁힌다. 그러지 않으면 자본변동표의 구성요소를 집는다.
    손익 항목은 IS 를 CIS 보다 먼저 본다 — 둘 다 있는 회사에서 IS 쪽이 본표이기 때문이다.
    """
    sections = WHICH_SECTIONS[metric]
    for section in sections:
        candidates = [r for r in rows if r.get("sj_div") == section]
        if not candidates:
            continue
        for account_id in ACCOUNT_IDS[metric]:
            for row in candidates:
                if (row.get("account_id") or "").strip() == account_id:
                    return row
        for name in ACCOUNT_NAMES[metric]:
            for row in candidates:
                if (row.get("account_nm") or "").strip() == name:
                    return row
    return None


def extract_years(rows: list[dict[str, str]], anchor_year: int) -> list[YearlyFinancial]:
    """응답 하나에서 3개 연도를 뽑아낸다.

    같은 계정 줄이 당기·전기·전전기 금액을 나란히 들고 있으므로, 줄을 한 번만 찾아 두고
    연도별 금액 칸만 바꿔 읽는다.
    """
    if not rows:
        return []

    found = {metric: _find_row(rows, metric) for metric in METRICS}
    currency = (rows[0].get("currency") or "KRW").strip() or "KRW"
    receipt_no = (rows[0].get("rcept_no") or "").strip()

    results: list[YearlyFinancial] = []
    for field, offset in PERIOD_FIELDS:
        values = {
            metric: _to_int(row.get(field)) if row is not None else None
            for metric, row in found.items()
        }
        # 그 해 값이 하나도 없으면 그 연도는 보고서에 없는 것이다. 빈 행을 만들지 않는다.
        if all(v is None for v in values.values()):
            continue
        results.append(
            YearlyFinancial(
                fiscal_year=anchor_year - offset,
                values=values,
                currency=currency,
                receipt_no=receipt_no,
            )
        )
    return results


def _save(corp_code: str, fs_div: str, years: list[YearlyFinancial]) -> int:
    if not years:
        return 0

    rows = [
        {
            "corp_code": corp_code,
            "fiscal_year": y.fiscal_year,
            "fs_div": fs_div,
            **y.values,
            "currency": y.currency,
            "receipt_no": y.receipt_no,
        }
        for y in years
    ]
    updatable = [c for c in rows[0] if c not in ("corp_code", "fiscal_year", "fs_div")]

    with get_session() as session:
        stmt = sqlite_insert(DartFinancial).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["corp_code", "fiscal_year", "fs_div"],
            set_={c: getattr(stmt.excluded, c) for c in updatable},
            # 같은 연도가 여러 보고서에 등장한다. 2023년 값은 2023년 사업보고서의 '당기'로도,
            # 2025년 사업보고서의 '전전기'로도 들어온다. 그런데 두 값이 다를 수 있다 —
            # 뒤 보고서에서 재작성(restatement)되기 때문이다(KB금융 2023 자본총계
            # 58.9조 → 58.6조). 항상 **더 나중에 제출된 보고서**의 값을 남긴다.
            # 접수번호가 YYYYMMDD###### 라 문자열 비교가 곧 제출 시점 비교다.
            where=sqlite_insert(DartFinancial).excluded.receipt_no > DartFinancial.receipt_no,
        )
        session.execute(stmt)
        session.commit()
    return len(rows)


def stored_years(corp_code: str, fs_div: str) -> set[int]:
    with get_session() as session:
        return set(
            session.execute(
                select(DartFinancial.fiscal_year)
                .where(DartFinancial.corp_code == corp_code)
                .where(DartFinancial.fs_div == fs_div)
            ).scalars()
        )


def load(corp_code: str, fs_div: str, years: int = 6) -> list[DartFinancial]:
    """저장된 재무 요약을 **오래된 연도부터** 돌려준다. 차트가 그대로 그릴 수 있는 순서다."""
    with get_session() as session:
        rows = list(
            session.execute(
                select(DartFinancial)
                .where(DartFinancial.corp_code == corp_code)
                .where(DartFinancial.fs_div == fs_div)
                .order_by(DartFinancial.fiscal_year.desc())
                .limit(years)
            ).scalars()
        )
    rows.reverse()
    return rows


def latest_annual_year(today: date | None = None) -> int:
    """지금 시점에 사업보고서가 나와 있을 만한 가장 최근 회계연도.

    사업보고서는 결산 후 90일 이내(대개 3월)에 나온다. 그래서 4월 전에는 재작년이,
    그 뒤로는 작년이 최신이다. 실제로 없으면 호출 쪽에서 한 해 더 거슬러 올라간다.
    """
    today = today or date.today()
    return today.year - 1 if today.month >= 4 else today.year - 2


async def ensure_financials(
    corp_code: str, *, years: int = 6, consolidated: bool = True
) -> tuple[str, int]:
    """필요한 연도의 재무 요약을 채운다. (실제 사용한 fs_div, 저장한 행 수) 를 돌려준다.

    응답 하나가 3개 연도를 담으므로 3년 간격으로만 부른다 — 6년치가 두 번이면 끝난다.
    이미 저장된 연도는 건너뛴다.

    연결(CFS)이 없는 회사는 별도(OFS)로 자동 전환한다. 종속회사가 없으면 연결재무제표를
    작성하지 않기 때문이다.
    """
    fs_div = "CFS" if consolidated else "OFS"
    latest = latest_annual_year()
    have = stored_years(corp_code, fs_div)

    # 3년 간격의 기준 연도들. 최신부터 거슬러 올라간다.
    anchors = [latest - offset for offset in range(0, years, 3)]
    saved = 0

    async with DartClient() as dart:
        for anchor in anchors:
            # 이 호출이 덮는 3개 연도가 이미 전부 있으면 부를 이유가 없다.
            if {anchor, anchor - 1, anchor - 2} <= have:
                continue

            used_year = anchor
            rows = await dart.get_financial_statements(
                corp_code, year=anchor, report_code=ANNUAL_REPORT, consolidated=(fs_div == "CFS")
            )

            # 가장 최근 연도조차 연결이 없으면 이 회사는 별도만 낸다. 한 번만 전환한다.
            if not rows and fs_div == "CFS" and anchor == anchors[0]:
                logger.info("%s: 연결재무제표가 없어 별도재무제표로 조회한다", corp_code)
                fs_div = "OFS"
                have = stored_years(corp_code, fs_div)
                rows = await dart.get_financial_statements(
                    corp_code, year=anchor, report_code=ANNUAL_REPORT, consolidated=False
                )

            if not rows:
                # 그 해 사업보고서의 전체 재무제표가 DART 에 없는 경우가 있다
                # (KB금융 2022 년이 그렇다. 2023 년은 정상이다). 한 해 뒤 보고서에는
                # 이 해가 '전기'로 들어 있으므로 그쪽에서 건져 온다.
                used_year = anchor + 1
                rows = await dart.get_financial_statements(
                    corp_code,
                    year=used_year,
                    report_code=ANNUAL_REPORT,
                    consolidated=(fs_div == "CFS"),
                )

            if not rows:
                logger.info("%s: %d 년 재무제표를 찾지 못했다", corp_code, anchor)
                continue

            extracted = extract_years(rows, used_year)
            # 동기 DB 쓰기다. 이벤트 루프를 붙잡지 않게 스레드로 뺀다.
            saved += await asyncio.to_thread(_save, corp_code, fs_div, extracted)
            have |= {y.fiscal_year for y in extracted}

    return fs_div, saved
