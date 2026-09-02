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

import math
import re
from decimal import Decimal

from sqlalchemy import func, select, update

from app.clients.sec import SecClient, SecError
from app.clients.toss import TossClient, TossError
from app.models.base import get_session
from app.models.us_company import SecCompany, SecFinancial
from app.services import sec_companies, sec_financials

logger = logging.getLogger(__name__)

# 토스 거래대금 랭킹에서 담는 수. 랭킹 자체가 상위 100종목까지만 덮는다.
DEFAULT_SIZE = 100

# 스크리너가 목표로 하는 유니버스 크기. 매출 상위 이만큼을 후보로 삼는다.
#
# 300 위가 연매출 15조원 선이다. 그 아래로 내려가면 회사 수는 늘지만 이름을 아는
# 회사는 빠르게 줄고, 회사당 3~4MB 인 적재 비용은 그대로다.
SCREEN_TARGET = 300

# 매출을 찾을 때 시도하는 태그. `services/sec_financials.py` 의 우선순위와 같은 순서다 —
# 회사마다 다른 태그를 쓰기 때문인데, 순서가 어긋나면 같은 회사가 다른 매출로 줄을 선다.
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
)

# 한 번에 시세를 물어보는 종목 수. 토스 시세 API 의 배치 상한이다.
PRICE_CHUNK = 200

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

# 발행주식수가 이보다 작으면 값을 잘못 읽은 것으로 본다.
#
# 실제로 Fox Corp 이 `1` 로 저장돼 있었다. 주식수가 1이면 시가총액이 주가 그 자체가
# 되어 PER 이 0.00 으로 나오고, 하필 '저PER' 정렬의 맨 윗줄을 차지한다. 값이 없어서
# 비는 것보다 나쁘다 — 틀린 숫자는 비어 있는 칸과 달리 사람이 믿는다.
MIN_PLAUSIBLE_SHARES = 1000


def _eligible_rows() -> list[tuple]:
    """스크리너에 설 자격이 있는 (CIK, 티커, 종가, 회사주식수, 티커주식수) 전부."""
    with get_session() as session:
        return [
            tuple(row)
            for row in session.execute(
                select(
                    SecCompany.cik,
                    SecCompany.ticker,
                    SecCompany.last_close,
                    SecCompany.shares_outstanding,
                    SecCompany.listed_shares,
                )
                # 주식수를 잘못 읽은 회사를 뺀다(위 MIN_PLAUSIBLE_SHARES 참고).
                # 둘 중 하나만 멀쩡해도 시가총액은 낼 수 있다 — 어느 쪽을 쓸지는
                # `valuation.us_shares` 가 정한다.
                .where(
                    func.coalesce(SecCompany.listed_shares, SecCompany.shares_outstanding)
                    >= MIN_PLAUSIBLE_SHARES
                )
                .where(SecCompany.sic.is_(None) | SecCompany.sic.notin_(FUND_SIC))
                .where(
                    select(SecFinancial.cik)
                    .where(SecFinancial.cik == SecCompany.cik)
                    .exists()
                )
            ).all()
        ]


def pricing_tickers() -> list[str]:
    """종가를 받아 둘 티커 **전부**. 대표만이 아니라 형제 티커까지 받는다.

    대표를 고를 때 "주가를 매길 수 있는가"를 쓰기 때문이다(`screen_universe`).
    형제의 주가를 안 받아 두면 그 판단을 할 수가 없다. 시세는 200종목 한 묶음이라
    몇백 개가 늘어도 호출 한두 번 차이다.
    """
    return sorted({row[1] for row in _eligible_rows()})


def screen_universe() -> list[str]:
    """스크리너가 훑을 미국 종목. **한 회사에 한 줄만 나온다.**

    세 가지를 거른다.

    **1. 회사가 아닌 것.** SIC 6221 은 상품신탁·ETF 다(위 `FUND_SIC` 참고).

    **2. 주식수를 잘못 읽은 회사.** 시가총액을 못 내므로 지표가 전부 헛값이 된다.

    **3. 같은 회사의 다른 종이.** 미국은 우선주(`JPM-PC`)·워런트(`DAICW`)·ETN 이
    본주와 **같은 CIK 를 쓴다.** SEC 재무는 CIK 단위라 그대로 두면 한 회사의 재무가
    티커 수만큼 복제된다. 실제로 ProShares Trust II 하나가 티커 16개로, JPMorgan 이
    9개로 들어와 있었다.

    ── 대표 티커를 고르는 규칙 ──────────────────────────────────────
    **먼저 주가를 매길 수 있는 것.** 값을 못 받는 티커가 대표가 되면 그 회사는
    PER 도 시총도 못 내면서 자리만 차지한다. 이 조건 하나가 실제 오답 둘을 고쳤다 —
    버크셔가 `BRK-A`(주당 수십만 달러라 시세가 안 온다) 대신 `BRK-B` 로, 푸르덴셜이
    회사채 `PFH` 대신 `PRU` 로 바뀐다.

    **그다음 짧은 것.** 우선주·워런트는 본주에 글자를 덧붙여 만든다(JPM → JPM-PC,
    DAIC → DAICW). 길이가 같으면 사전순으로 끊는다.

    **그다음 주식수가 맞는 것.** 티커 글자만으로는 어느 쪽이 보통주인지 알 수 없다 —
    컴캐스트의 파생 증권 `CCZ` 는 본주 `CMCSA` 보다 짧고 시세도 온다. 대신 **숫자로**
    가린다. SEC 가 회사 단위로 보고한 주식수와, 토스가 티커별로 주는 상장주식수를
    견주어 가장 가까운 쪽을 고른다. 보통주는 회사가 보고한 수와 자릿수가 맞고,
    우선주·채권은 몇 자릿수씩 어긋난다 — CCZ 258만주 대 CMCSA 35억주, 프루덴셜
    본주 3.45억주(SEC 보고치와 정확히 일치) 대 후순위채 4.22억주.

    **마지막으로 짧은 것.** 우선주·워런트는 본주에 글자를 덧붙여 만든다(JPM → JPM-PC,
    DAIC → DAICW). 길이가 같으면 사전순으로 끊는다.

    주식수를 모르는 티커는 이 비교에서 빠지고 길이 규칙으로 넘어간다. 버크셔가
    그렇다 — 토스가 `BRK-A`·`BRK-B` 어느 쪽도 다루지 않아 가릴 근거가 없다.
    """
    best: dict[str, tuple] = {}
    for cik, ticker, close, company_shares, listed in _eligible_rows():
        current = best.get(cik)
        key = (
            # 주가가 있는 쪽이 먼저. 값을 못 매기는 티커가 대표가 되면 그 회사는
            # PER 도 시총도 못 내면서 자리만 차지한다.
            0 if close is not None else 1,
            _share_gap(company_shares, listed),
            len(ticker),
            ticker,
        )
        if current is None or key < current:
            best[cik] = key
    return sorted(key[3] for key in best.values())


def _share_gap(company_shares: int | None, listed: int | None) -> float:
    """회사가 보고한 주식수와 이 티커의 상장주식수가 몇 자릿수 어긋나는가.

    작을수록 보통주에 가깝다. 둘 중 하나라도 없으면 판단하지 않는다 — 큰 값을
    돌려주어 아는 티커에게 자리를 내주되, 모두 모르면 다음 기준(길이)으로 넘어간다.
    """
    if not company_shares or not listed:
        return 99.0
    return abs(math.log10(listed / company_shares))


async def candidates(period: str, *, target: int = SCREEN_TARGET) -> list[str]:
    """스크리너가 담을 후보를 **매출 큰 순으로** 고른다.

    ── 왜 이 방법인가 ────────────────────────────────────────────────
    지금까지 후보는 토스 거래대금 랭킹에서 왔는데, **그 랭킹이 상위 100종목까지만
    덮는다.** 유니버스가 작았던 진짜 원인이 여기다. 재무를 아무리 열심히 받아도
    100개 밖의 회사는 애초에 후보로 올라오지 못했다.

    SEC 의 **횡단면**(`frames`)은 그 벽이 없다. "2025년 매출"을 한 번 물으면 4천여
    회사가 한꺼번에 온다. 거기서 우리가 티커를 아는 회사만 남기고 매출 순으로 자른다.

    ── 왜 매출로 줄 세우나 ──────────────────────────────────────────
    시가총액으로 세우는 편이 스크리너답지만 그러려면 후보 전부의 주가가 먼저
    있어야 한다 — 후보를 고르려고 후보를 알아야 하는 순환이다. 매출은 SEC 가
    그냥 준다. "매출 상위 N개"는 화면에 그대로 적어 설명할 수 있는 기준이기도 하다.

    ── 여기서 받은 숫자는 화면에 나가지 않는다 ──────────────────────
    누구를 담을지만 정하고, 화면의 매출·이익은 지금처럼 회사별 `companyfacts` 에서
    낸다. 출처가 갈리면 같은 종목의 매출이 목록과 상세에서 다르게 보인다.
    """
    revenue: dict[str, int] = {}
    async with SecClient() as sec:
        for tag in REVENUE_TAGS:
            try:
                rows = await sec.get_frame(tag, period=period)
            except SecError as exc:
                # 그 해에 아무도 쓰지 않은 태그는 404 다. 정상이므로 다음 태그로 넘어간다.
                logger.info("횡단면 %s/%s 없음 — %s", tag, period, exc)
                continue
            for row in rows:
                cik = str(row.get("cik") or "").strip().zfill(10)
                value = row.get("val")
                if not cik or value is None:
                    continue
                # 앞선 태그가 이미 값을 냈으면 그것을 쓴다(태그 우선순위).
                revenue.setdefault(cik, int(value))

    if not revenue:
        return []

    representative = _representative_tickers()
    ranked = sorted(
        ((value, representative[cik]) for cik, value in revenue.items() if cik in representative),
        reverse=True,
    )
    return [ticker for _, ticker in ranked[:target]]


def _representative_tickers() -> dict[str, str]:
    """CIK 하나에 티커 하나. `screen_universe` 와 같은 규칙으로 고른다."""
    with get_session() as session:
        rows = session.execute(
            select(SecCompany.cik, SecCompany.ticker).where(
                SecCompany.sic.is_(None) | SecCompany.sic.notin_(FUND_SIC)
            )
        ).all()

    best: dict[str, str] = {}
    for cik, ticker in rows:
        current = best.get(cik)
        if current is None or (len(ticker), ticker) < (len(current), current):
            best[cik] = ticker
    return best


def not_loaded(tickers: list[str]) -> list[str]:
    """이 후보들 중 **아직 재무를 받지 않은 것.** 순서는 그대로 둔다.

    밤마다 조금씩 받을 때 필요하다. 후보 목록의 앞에서 그냥 잘라 내면, 앞쪽 회사가
    다 채워진 뒤로는 매번 같은 것을 다시 훑고 뒤쪽은 영영 차례가 오지 않는다.
    """
    if not tickers:
        return []
    with get_session() as session:
        have = {
            row[0]
            for row in session.execute(
                select(SecCompany.ticker)
                .where(SecCompany.ticker.in_(tickers))
                # **발행주식수까지 있어야 다 받은 것으로 친다.** 재무만 있고 주식수가
                # 없으면 시가총액을 못 내 스크리너에 나오지 못하는데, 재무만 보고
                # 넘기면 그 회사는 영영 미완인 채로 남는다. `ensure_financials` 도
                # 같은 이유로 주식수가 비면 연도 수와 상관없이 다시 받는다.
                .where(SecCompany.shares_outstanding.isnot(None))
                .where(SecCompany.shares_outstanding > 0)
                .where(
                    select(SecFinancial.cik)
                    .where(SecFinancial.cik == SecCompany.cik)
                    .exists()
                )
            ).all()
        }
    return [t for t in tickers if t not in have]


# 보통주가 아닌 증권을 이름으로 가린다. SEC 에는 증권 종류를 알려 주는 항목이 없고,
# 티커 글자로도 알 수 없다. 토스가 주는 이름에는 또렷이 적혀 있다 —
# "컴캐스트 홀딩스 우선주", "듀크 에너지 2078년 만기 후순위 채권".
#
# 이것을 쓰는 곳은 **시가총액을 합산할 때뿐이다**(`common_market_caps`).
# 이름 표기가 바뀌어도 나머지 계산은 영향을 받지 않는다.
NOT_COMMON = re.compile(r"우선주|채권|워런트|신주인수권|전환사채|권리")


def common_market_caps() -> dict[str, Decimal]:
    """보통주가 **둘 이상**인 회사의 시가총액. 그런 회사가 아니면 담지 않는다.

    한 회사가 클래스 여럿으로 상장돼 있으면 한 클래스만 세어서는 시가총액이 안 된다.
    버크셔가 그렇다 — A주 $369B, B주 $711B 로 합쳐야 $1,080B 다. 대표 티커 하나로
    내면 3분의 1만 잡히고, 그러면 PER 도 3분의 1이 되어 '저PER' 맨 위로 올라온다.
    마스터카드·Fox 와 같은 실패 방식이다.

    **293곳 중 이런 회사는 버크셔 하나다.** 그래서 여기 담기는 것도 그 하나뿐이고,
    나머지는 지금까지 하던 계산을 그대로 쓴다(`valuation.us_screen_rows`). 한 곳을
    위해 292곳의 숫자가 달라지는 일은 없다.

    우선주·채권은 자기자본이 아니므로 뺀다. 이것을 안 하면 우선주를 여럿 발행한
    은행들의 시가총액이 부풀어 오른다.
    """
    with get_session() as session:
        rows = session.execute(
            select(
                SecCompany.cik,
                SecCompany.listed_name,
                SecCompany.listed_shares,
                SecCompany.last_close,
            )
            .where(SecCompany.listed_shares.isnot(None))
            .where(SecCompany.last_close.isnot(None))
        ).all()

    by_cik: dict[str, list[Decimal]] = {}
    for cik, name, shares, close in rows:
        if name and NOT_COMMON.search(name):
            continue
        by_cik.setdefault(cik, []).append(Decimal(shares) * Decimal(close))

    return {cik: sum(values) for cik, values in by_cik.items() if len(values) > 1}


def _toss_aliases(tickers: list[str]) -> dict[str, str]:
    """토스에 물어볼 표기 → 우리 티커.

    **같은 종목을 서로 다른 문자로 부른다.** SEC 는 종류주식을 하이픈으로 쓰고
    (`BRK-B`) 토스는 점으로 쓴다(`BRK.B`). 그대로 물으면 빈손으로 돌아오는데,
    없는 종목과 구별이 안 되어 "토스가 다루지 않는 종목"으로 보인다. 실제로
    버크셔가 그렇게 오해되어 주가도 시가총액도 없이 목록에 서 있었다.

    두 표기를 모두 물어본다. 어느 쪽으로 답이 오든 우리 티커에 담는다 —
    토스가 하이픈 표기를 쓰는 종목이 있어도 잃지 않는다. 시세는 200종목 한
    묶음이라 물어볼 것이 몇십 개 늘어도 호출 한 번 차이다.
    """
    alias: dict[str, str] = {}
    for ticker in tickers:
        alias[ticker] = ticker
        if "-" in ticker:
            alias[ticker.replace("-", ".")] = ticker
    return alias


def closes_as_of() -> str | None:
    """받아 둔 주가 중 가장 늦은 시각. 화면이 "언제 값인지"를 밝히는 데 쓴다.

    미국에는 확정 종가라는 개념이 없어 국내처럼 날짜 하나로 못 적는다. 장중에 받은
    값과 마감 뒤에 받은 값이 다른 뜻이므로 시각까지 남긴다.
    """
    with get_session() as session:
        latest = session.execute(
            select(SecCompany.last_close_at)
            .where(SecCompany.last_close_at.isnot(None))
            .order_by(SecCompany.last_close_at.desc())
            .limit(1)
        ).scalar()
    return latest.isoformat() if latest else None


async def refresh_listed_shares(tickers: list[str]) -> int:
    """티커별 상장주식수를 받아 둔다. 대표 티커를 가리는 데만 쓴다.

    시세와 달리 자주 바뀌지 않지만 같은 배치 상한(200)을 쓰므로 함께 돌려도 값이 싸다.
    """
    if not tickers:
        return 0
    alias = _toss_aliases(tickers)
    asked = sorted(alias)
    saved = 0
    async with TossClient() as toss:
        for start in range(0, len(asked), PRICE_CHUNK):
            chunk = asked[start : start + PRICE_CHUNK]
            try:
                rows = await toss.get_stocks(chunk)
            except TossError:
                logger.warning("상장주식수 갱신 실패 — %s 외 %d종목", chunk[0], len(chunk) - 1)
                continue
            saved += await asyncio.to_thread(_save_listed_shares, rows, alias)
    return saved


def _save_listed_shares(rows: list[dict], alias: dict[str, str]) -> int:
    saved = 0
    with get_session() as session:
        for row in rows:
            ticker = alias.get(row.get("symbol"))
            shares = row.get("sharesOutstanding")
            if not ticker or shares in (None, ""):
                continue
            result = session.execute(
                update(SecCompany)
                .where(SecCompany.ticker == ticker)
                .values(listed_shares=int(shares), listed_name=row.get("name"))
            )
            saved += result.rowcount or 0
        session.commit()
    return saved


async def refresh_closes(tickers: list[str]) -> int:
    """후보들의 주가를 받아 저장한다. 저장한 종목 수를 돌려준다.

    **스크리너가 실시간 폴러를 쓰지 않게 하려는 것이다.** 조회할 때마다 유니버스를
    폴러에 등록하면 웹소켓 구독 한도(100종목)를 스크리너가 먹어 치워, 사용자가 보고
    있던 종목이 실시간에서 소리 없이 밀려난다. 미리 받아 두고 DB 만 읽게 한다.

    시세 API 는 한 번에 200종목까지 받으므로 몇 번이면 끝난다 — 300종목에 두 번이다.
    회사당 3~4MB 인 재무 적재와 달리 이쪽은 값이 싸서 매일 돌려도 부담이 없다.
    """
    if not tickers:
        return 0

    now = datetime.now(timezone.utc)
    alias = _toss_aliases(tickers)
    asked = sorted(alias)
    saved = 0
    async with TossClient() as toss:
        for start in range(0, len(asked), PRICE_CHUNK):
            chunk = asked[start : start + PRICE_CHUNK]
            try:
                rows = await toss.get_prices(chunk)
            except TossError:
                # 한 묶음이 실패해도 나머지는 받는다. 값이 없는 종목은 지표가 빌 뿐이다.
                logger.warning("미국 종가 갱신 실패 — %s 외 %d종목", chunk[0], len(chunk) - 1)
                continue
            saved += await asyncio.to_thread(_save_closes, rows, now, alias)
    return saved


def _save_closes(rows: list[dict], at: datetime, alias: dict[str, str]) -> int:
    saved = 0
    with get_session() as session:
        for row in rows:
            ticker = alias.get(row.get("symbol"))
            price = row.get("lastPrice")
            if not ticker or price in (None, ""):
                continue
            result = session.execute(
                update(SecCompany)
                .where(SecCompany.ticker == ticker)
                .values(last_close=Decimal(str(price)), last_close_at=at)
            )
            saved += result.rowcount or 0
        session.commit()
    return saved


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
