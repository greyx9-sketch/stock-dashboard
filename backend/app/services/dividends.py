"""배당 정보를 OpenDART 에서 받아 저장한다.

응답이 재무제표와 전혀 다른 모양이다. 계정 ID 로 찾는 XBRL 이 아니라, `se`(구분)에
**한글 문자열**이 들어 있는 표다. 실제 응답(2026-08-24 삼성전자 2025년 확인):

    {"se": "주당 현금배당금(원)",   "stock_knd": "보통주", "thstrm": "1,668", ...}
    {"se": "현금배당수익률(%)",     "stock_knd": "우선주", "thstrm": "1.90",  ...}
    {"se": "현금배당금총액(백만원)", "stock_knd": "-",      "thstrm": "11,107,906", ...}

그래서 **문자열을 느슨하게 맞춘다.** 회사마다 띄어쓰기가 다를 수 있어서 공백을 걷어내고
비교한다. 정확히 일치하는 항목이 없으면 그 값은 없는 것으로 둔다 — 지어내지 않는다.

`thstrm`(당기)만 쓴다. `frmtrm`·`lwfr`(전기·전전기)도 오지만, 그 해들은 각각의
사업보고서에서 받는 편이 낫다 — 나중에 정정되면 최신 보고서 쪽이 맞기 때문이다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.clients.dart import ANNUAL_REPORT, DartClient
from app.models.base import get_session
from app.models.dividend import DartDividend

logger = logging.getLogger(__name__)

# 찾을 항목. 공백을 걷어낸 뒤 비교하므로 여기서도 공백 없이 적는다.
SE_DPS = "주당현금배당금(원)"
SE_YIELD = "현금배당수익률(%)"
SE_TOTAL = "현금배당금총액(백만원)"

COMMON = "보통주"
PREFERRED = "우선주"

# DART 가 총액을 백만원으로 준다. 이 프로젝트의 금액 단위는 원이다.
MILLION = 1_000_000


@dataclass(frozen=True)
class Dividend:
    fiscal_year: int
    dps_common: int | None
    dps_preferred: int | None
    total_cash: int | None
    reported_yield: float | None
    settlement_date: str | None
    receipt_no: str


def _clean(value: str | None) -> str:
    return (value or "").replace(" ", "").strip()


def _number(raw: str | None) -> float | None:
    """DART 숫자 문자열 → 실수. 빈 값·'-' 는 없는 값이다.

    배당을 하지 않은 해는 '-' 로 온다. 그것을 0 으로 바꾸면 "배당 0원"이 되는데,
    "배당을 안 했다"와 "0원을 줬다"는 화면에서 다르게 읽혀야 한다.
    """
    text = (raw or "").replace(",", "").strip()
    if text in ("", "-", "－"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pick(rows: list[dict[str, str]], se: str, kind: str | None) -> float | None:
    """그 구분·주식종류에 해당하는 당기 값. 없으면 None.

    `kind` 가 None 이면 주식종류를 따지지 않는다(총액처럼 하나뿐인 항목).
    """
    for row in rows:
        if _clean(row.get("se")) != se:
            continue
        if kind is not None and _clean(row.get("stock_knd")) != kind:
            continue
        return _number(row.get("thstrm"))
    return None


def extract(rows: list[dict[str, str]], year: int) -> Dividend | None:
    """배당 응답 한 덩어리에서 필요한 값만 뽑는다. 쓸 것이 없으면 None."""
    if not rows:
        return None

    dps_common = _pick(rows, SE_DPS, COMMON)
    dps_preferred = _pick(rows, SE_DPS, PREFERRED)
    total = _pick(rows, SE_TOTAL, None)
    # 수익률은 보통주 기준을 쓴다. 우선주 종목의 수익률은 어차피 현재가로 다시 계산한다.
    reported = _pick(rows, SE_YIELD, COMMON)

    if all(v is None for v in (dps_common, dps_preferred, total)):
        return None

    return Dividend(
        fiscal_year=year,
        dps_common=int(dps_common) if dps_common is not None else None,
        dps_preferred=int(dps_preferred) if dps_preferred is not None else None,
        total_cash=int(total * MILLION) if total is not None else None,
        reported_yield=reported,
        settlement_date=(rows[0].get("stlm_dt") or "").strip() or None,
        receipt_no=(rows[0].get("rcept_no") or "").strip(),
    )


def _save(corp_code: str, item: Dividend) -> None:
    row = {
        "corp_code": corp_code,
        "fiscal_year": item.fiscal_year,
        "dps_common": item.dps_common,
        "dps_preferred": item.dps_preferred,
        "total_cash": item.total_cash,
        "reported_yield": item.reported_yield,
        "settlement_date": item.settlement_date,
        "receipt_no": item.receipt_no,
    }
    updatable = [c for c in row if c not in ("corp_code", "fiscal_year")]

    with get_session() as session:
        stmt = sqlite_insert(DartDividend).values([row])
        stmt = stmt.on_conflict_do_update(
            index_elements=["corp_code", "fiscal_year"],
            set_={c: getattr(stmt.excluded, c) for c in updatable},
            # 정정보고서가 나중에 올 수 있다. 항상 더 나중에 제출된 것을 남긴다
            # (접수번호가 YYYYMMDD###### 라 문자열 비교가 곧 제출 시점 비교다).
            where=sqlite_insert(DartDividend).excluded.receipt_no > DartDividend.receipt_no,
        )
        session.execute(stmt)
        session.commit()


def latest(corp_code: str) -> DartDividend | None:
    """가장 최근 회계연도의 배당. 없으면 None."""
    with get_session() as session:
        return session.execute(
            select(DartDividend)
            .where(DartDividend.corp_code == corp_code)
            .order_by(DartDividend.fiscal_year.desc())
            .limit(1)
        ).scalars().first()


def stored_years(corp_code: str) -> set[int]:
    with get_session() as session:
        return set(
            session.execute(
                select(DartDividend.fiscal_year).where(DartDividend.corp_code == corp_code)
            ).scalars()
        )


async def ensure_dividends(corp_code: str, years: list[int]) -> int:
    """그 회계연도들의 배당을 채운다. 저장한 해의 수를 돌려준다.

    **한 해에 한 번씩 부른다.** 응답에 전기·전전기도 들어 있지만 쓰지 않는다 — 그 해들은
    각자의 사업보고서에서 받는 편이 낫다(나중에 정정되면 최신 보고서 쪽이 맞다).
    이미 저장된 해는 건너뛴다.
    """
    have = stored_years(corp_code)
    todo = [y for y in years if y not in have]
    if not todo:
        return 0

    saved = 0
    async with DartClient() as dart:
        for year in todo:
            rows = await dart.get_dividends(corp_code, year=year, report_code=ANNUAL_REPORT)
            item = extract(rows, year)
            if item is None:
                # 배당을 하지 않는 회사도 많다. 오류가 아니다.
                continue
            await asyncio.to_thread(_save, corp_code, item)
            saved += 1
    return saved
