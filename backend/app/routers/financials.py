"""재무 조회 엔드포인트.

**모든 수치는 XBRL 계정값에서 직접 계산한다**(CLAUDE.md 절대 규칙 3).
마진·성장률·부채비율은 여기서 원값으로 나눗셈해 만든다. LLM 은 이 경로에 관여하지 않는다.

파생값을 DB 에 저장하지 않는 이유도 같다. 원값과 계산값을 따로 저장하면 나중에 원값이
재작성됐을 때 둘이 어긋나고, 어느 쪽이 맞는지 알 수 없게 된다.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.clients.dart import DartError
from app.models.financial import DartFinancial
from app.models.quarterly import DartQuarterly
from app.services import dart_corps, dart_financials, dart_quarterly
from app.services import dividends as dividends_service
from app.services import valuation as valuation_service

router = APIRouter(prefix="/api/stocks", tags=["재무"])

FS_LABEL = {"CFS": "연결", "OFS": "별도"}


class FinancialYear(BaseModel):
    """한 회계연도의 재무 수치. 파생값은 전부 원값에서 계산한 것이다."""

    fiscal_year: int
    revenue: int | None = Field(description="매출액 (원). 금융지주 등 없는 회사도 있다")
    gross_profit: int | None
    operating_income: int | None = Field(description="영업이익 (원)")
    net_income: int | None = Field(description="당기순이익 (원)")
    total_assets: int | None
    total_liabilities: int | None
    total_equity: int | None

    operating_margin: Decimal | None = Field(description="영업이익률 (%) = 영업이익/매출액")
    net_margin: Decimal | None = Field(description="순이익률 (%) = 당기순이익/매출액")
    revenue_growth: Decimal | None = Field(description="매출 증가율 (%) — 전년 대비")
    operating_income_growth: Decimal | None = Field(description="영업이익 증가율 (%)")
    roe: Decimal | None = Field(description="자기자본이익률 (%) = 당기순이익/자본총계")
    debt_ratio: Decimal | None = Field(description="부채비율 (%) = 부채총계/자본총계")

    receipt_no: str = Field(description="이 값이 나온 보고서의 접수번호")
    source_url: str = Field(description="원문 보기 주소")


class FinancialsOut(BaseModel):
    stock_code: str
    corp_name: str
    corp_code: str
    fs_div: str = Field(description="CFS 연결 / OFS 별도")
    fs_label: str = Field(description="화면에 쓸 이름")
    currency: str
    years: list[FinancialYear] = Field(description="오래된 연도부터")


def _pct(numerator: int | None, denominator: int | None) -> Decimal | None:
    """백분율. 분모가 없거나 0 이면 계산하지 않는다.

    분모가 음수인 경우(자본잠식 등)도 그대로 계산한다 — 숫자를 감추면 더 위험하다.
    """
    if numerator is None or denominator is None or denominator == 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * 100).quantize(Decimal("0.01"))


def _growth(current: int | None, previous: int | None) -> Decimal | None:
    """전년 대비 증가율.

    전년이 적자(음수)면 증가율이 뜻을 잃는다(-100억 → +50억이 '150% 성장'이 아니다).
    그런 경우는 계산하지 않고 비운다. 화면에서 "-" 로 보이는 편이 틀린 숫자보다 낫다.
    """
    if current is None or previous is None or previous <= 0:
        return None
    return ((Decimal(current) - Decimal(previous)) / Decimal(previous) * 100).quantize(
        Decimal("0.01")
    )


def _to_year(row: DartFinancial, previous: DartFinancial | None) -> FinancialYear:
    return FinancialYear(
        fiscal_year=row.fiscal_year,
        revenue=row.revenue,
        gross_profit=row.gross_profit,
        operating_income=row.operating_income,
        net_income=row.net_income,
        total_assets=row.total_assets,
        total_liabilities=row.total_liabilities,
        total_equity=row.total_equity,
        operating_margin=_pct(row.operating_income, row.revenue),
        net_margin=_pct(row.net_income, row.revenue),
        revenue_growth=_growth(row.revenue, previous.revenue if previous else None),
        operating_income_growth=_growth(
            row.operating_income, previous.operating_income if previous else None
        ),
        # **ROE 도 지배주주 몫으로 낸다.** 바로 위 밸류에이션 블록의 PER·PBR 이 그 기준인데
        # 여기만 전체로 내면 한 화면 안에서 기준이 갈린다(카카오: 전체 3.40% / 지배주주
        # 4.35%). 지배주주 몫이 없는 행 — 별도재무제표이거나 아직 다시 받지 않은 행 —
        # 은 전체로 물러선다.
        roe=_pct(
            row.net_income_owners if row.net_income_owners is not None else row.net_income,
            row.total_equity_owners if row.total_equity_owners is not None else row.total_equity,
        ),
        debt_ratio=_pct(row.total_liabilities, row.total_equity),
        receipt_no=row.receipt_no,
        source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row.receipt_no}",
    )


@router.get("/{symbol}/financials", summary="연간 재무 (매출·이익·재무상태)")
async def get_financials(
    symbol: str = Path(description="단축코드 6자리 (예: 005930)", pattern=r"^\d{6}$"),
    years: int = Query(6, ge=2, le=12, description="가져올 회계연도 수"),
) -> FinancialsOut:
    """연간 재무 요약을 **오래된 연도부터** 돌려준다.

    사업보고서 기준이다. 분기·반기는 누적/당분기 구분이 섞여 있어 연간과 같은 방식으로
    다룰 수 없으므로 이 단계에서는 다루지 않는다.

    처음 조회하는 종목은 OpenDART 를 2~4회 부르느라 몇 초 걸린다. 이후에는 DB 에서 읽는다.
    """
    corp = dart_corps.get_corp(symbol)
    if corp is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{symbol}' 의 DART 고유번호를 찾지 못했습니다. 비상장 종목일 수 있습니다.",
        )

    try:
        fs_div, _ = await dart_financials.ensure_financials(corp.corp_code, years=years)
    except DartError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    rows = dart_financials.load(corp.corp_code, fs_div, years=years)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{corp.corp_name}' 의 재무제표를 찾지 못했습니다.\n"
                "신규 상장이라 사업보고서가 아직 없거나, DART 에 전체 재무제표가 "
                "올라오지 않은 회사일 수 있습니다."
            ),
        )

    return FinancialsOut(
        stock_code=symbol,
        corp_name=corp.corp_name,
        corp_code=corp.corp_code,
        fs_div=fs_div,
        fs_label=FS_LABEL.get(fs_div, fs_div),
        currency=rows[-1].currency,
        # 앞 연도가 있어야 증가율을 낼 수 있다. rows 는 오래된 연도부터라 인덱스로 짚는다.
        years=[_to_year(row, rows[i - 1] if i > 0 else None) for i, row in enumerate(rows)],
    )


# ====================================================================== 분기·반기


class QuarterPoint(BaseModel):
    """한 분기의 재무 수치.

    **두 기준을 함께 담는다.** 화면이 3개월/누적을 전환하는데, 둘 다 보고서에 적힌
    원값이라 어느 쪽도 계산으로 만들지 않는다(4분기만 예외 — `derived` 참고).
    """

    fiscal_year: int
    quarter: int = Field(description="1~4")
    label: str = Field(description="화면에 쓸 이름 (예: 2025 3Q)")
    derived: bool = Field(
        description=(
            "4분기의 3개월 손익은 DART 에 보고서가 없어 '연간 − 3분기 누적'으로 계산한 "
            "값이다. 그때만 참. 누적값과 재무상태는 사업보고서의 원값이라 계산이 아니다."
        )
    )

    # 당분기 3개월
    revenue: int | None
    gross_profit: int | None
    operating_income: int | None
    net_income: int | None

    # 연초부터 누적
    revenue_cum: int | None
    gross_profit_cum: int | None
    operating_income_cum: int | None
    net_income_cum: int | None

    # 분기말 잔액. 누적이라는 개념이 없다.
    total_assets: int | None
    total_liabilities: int | None
    total_equity: int | None

    operating_margin: Decimal | None = Field(description="영업이익률 (%) — 3개월 기준")
    net_margin: Decimal | None = Field(description="순이익률 (%) — 3개월 기준")
    operating_margin_cum: Decimal | None = Field(description="영업이익률 (%) — 누적 기준")
    net_margin_cum: Decimal | None = Field(description="순이익률 (%) — 누적 기준")

    # ROE 는 내지 않는다. 순이익은 3개월치인데 자본은 잔액이라 둘을 나누면 연간과
    # 견줄 수 없는 숫자가 된다(연율로 고치는 것은 또 다른 가정이다).
    debt_ratio: Decimal | None = Field(
        description="부채비율 (%) = 부채총계/자본총계. 둘 다 분기말 잔액이라 분기에도 성립한다"
    )

    revenue_yoy: Decimal | None = Field(description="매출 증가율 (%) — 전년 동분기 대비")
    operating_income_yoy: Decimal | None = Field(description="영업이익 증가율 (%) — 전년 동분기")
    revenue_cum_yoy: Decimal | None = Field(description="누적 매출 증가율 (%) — 전년 같은 시점")
    operating_income_cum_yoy: Decimal | None = Field(description="누적 영업이익 증가율 (%)")

    receipt_no: str
    source_url: str


class QuarterlyOut(BaseModel):
    stock_code: str
    corp_name: str
    corp_code: str
    fs_div: str = Field(description="CFS 연결 / OFS 별도")
    fs_label: str
    currency: str
    quarters: list[QuarterPoint] = Field(description="오래된 분기부터")


def _minus(total: int | None, part: int | None) -> int | None:
    """`연간 − 3분기 누적`. 한쪽이라도 없으면 계산하지 않는다.

    음수가 나와도 그대로 둔다 — 4분기에 적자를 낸 회사가 실제로 그렇다.
    """
    if total is None or part is None:
        return None
    return total - part


def _q4_from_annual(annual: DartFinancial, q3: dict | None) -> dict | None:
    """4분기 한 행을 만든다. DART 에 4분기 보고서가 없어 여기서 구한다.

    - **3개월 손익** = 연간 − 3분기 누적. 이것만 계산값이다(`derived=True`).
    - **누적 손익** = 연간 그 자체. 4분기까지의 누적이 곧 한 해 전체다.
    - **재무상태** = 사업보고서의 기말 잔액. 계산이 아니라 원값이다.

    3분기 누적이 없으면 4분기 3개월치를 만들 수 없다. 그때는 아예 만들지 않는다 —
    연간값을 4분기인 척 보여주면 네 배 부풀려진 막대가 그려진다.
    """
    if q3 is None:
        return None

    # q3 는 `_as_dict` 를 거친 dict 다. 4분기도 같은 모양으로 돌려주므로 이 함수 앞뒤가
    # 전부 dict 하나로 통일된다 — 모델 객체와 dict 를 섞으면 여기서 헷갈린다.
    three_month = {
        "revenue": _minus(annual.revenue, q3["revenue_cum"]),
        "gross_profit": _minus(annual.gross_profit, q3["gross_profit_cum"]),
        "operating_income": _minus(annual.operating_income, q3["operating_income_cum"]),
        "net_income": _minus(annual.net_income, q3["net_income_cum"]),
    }
    if all(v is None for v in three_month.values()):
        return None

    return {
        "fiscal_year": annual.fiscal_year,
        "quarter": 4,
        "derived": True,
        **three_month,
        "revenue_cum": annual.revenue,
        "gross_profit_cum": annual.gross_profit,
        "operating_income_cum": annual.operating_income,
        "net_income_cum": annual.net_income,
        "total_assets": annual.total_assets,
        "total_liabilities": annual.total_liabilities,
        "total_equity": annual.total_equity,
        "currency": annual.currency,
        "receipt_no": annual.receipt_no,
    }


def _as_dict(row: DartQuarterly) -> dict:
    """DB 행을 4분기 계산 결과와 같은 모양으로 맞춘다. 그 뒤 처리를 하나로 합치려는 것이다."""
    return {
        "fiscal_year": row.fiscal_year,
        "quarter": row.quarter,
        "derived": False,
        "revenue": row.revenue,
        "gross_profit": row.gross_profit,
        "operating_income": row.operating_income,
        "net_income": row.net_income,
        "revenue_cum": row.revenue_cum,
        "gross_profit_cum": row.gross_profit_cum,
        "operating_income_cum": row.operating_income_cum,
        "net_income_cum": row.net_income_cum,
        "total_assets": row.total_assets,
        "total_liabilities": row.total_liabilities,
        "total_equity": row.total_equity,
        "currency": row.currency,
        "receipt_no": row.receipt_no,
    }


def _to_quarter(point: dict, year_ago: dict | None) -> QuarterPoint:
    """파생값을 붙여 응답 모양으로 만든다. 전년 동분기는 증가율에만 쓴다."""
    prev = year_ago or {}
    return QuarterPoint(
        fiscal_year=point["fiscal_year"],
        quarter=point["quarter"],
        label=f"{point['fiscal_year']} {point['quarter']}Q",
        derived=point["derived"],
        revenue=point["revenue"],
        gross_profit=point["gross_profit"],
        operating_income=point["operating_income"],
        net_income=point["net_income"],
        revenue_cum=point["revenue_cum"],
        gross_profit_cum=point["gross_profit_cum"],
        operating_income_cum=point["operating_income_cum"],
        net_income_cum=point["net_income_cum"],
        total_assets=point["total_assets"],
        total_liabilities=point["total_liabilities"],
        total_equity=point["total_equity"],
        operating_margin=_pct(point["operating_income"], point["revenue"]),
        net_margin=_pct(point["net_income"], point["revenue"]),
        operating_margin_cum=_pct(point["operating_income_cum"], point["revenue_cum"]),
        net_margin_cum=_pct(point["net_income_cum"], point["revenue_cum"]),
        debt_ratio=_pct(point["total_liabilities"], point["total_equity"]),
        # **전분기가 아니라 전년 동분기와 견준다.** 분기 실적은 계절을 심하게 타서
        # 직전 분기와 비교하면 해마다 같은 자리에서 같은 착시가 생긴다.
        revenue_yoy=_growth(point["revenue"], prev.get("revenue")),
        operating_income_yoy=_growth(point["operating_income"], prev.get("operating_income")),
        revenue_cum_yoy=_growth(point["revenue_cum"], prev.get("revenue_cum")),
        operating_income_cum_yoy=_growth(
            point["operating_income_cum"], prev.get("operating_income_cum")
        ),
        receipt_no=point["receipt_no"],
        source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={point['receipt_no']}",
    )


@router.get("/{symbol}/financials/quarterly", summary="분기·반기 재무")
async def get_quarterly_financials(
    symbol: str = Path(description="단축코드 6자리 (예: 005930)", pattern=r"^\d{6}$"),
    quarters: int = Query(12, ge=4, le=20, description="가져올 분기 수"),
) -> QuarterlyOut:
    """분기 재무를 **오래된 분기부터** 돌려준다.

    한 분기마다 두 기준을 함께 담는다 — **당분기 3개월**과 **연초부터 누적**. 둘 다
    보고서에 적힌 원값이다.

    **4분기는 DART 에 보고서가 없다.** 사업보고서가 그 자리를 대신하므로 4분기의 3개월
    손익만 `연간 − 3분기 누적`으로 계산해 채우고 `derived` 를 참으로 표시한다.

    처음 조회하는 종목은 OpenDART 를 여러 번 부르느라 십여 초 걸린다. 이후에는 DB 에서
    읽고, 새 분기가 하나 늘 때마다 한 번씩만 더 부른다.
    """
    corp = dart_corps.get_corp(symbol)
    if corp is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{symbol}' 의 DART 고유번호를 찾지 못했습니다. 비상장 종목일 수 있습니다.",
        )

    # 분기를 채우려면 연간도 있어야 한다 — 4분기가 연간에서 나온다.
    try:
        annual_div, _ = await dart_financials.ensure_financials(corp.corp_code, years=4)
        fs_div, _ = await dart_quarterly.ensure_quarterly(corp.corp_code, years=3)
    except DartError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    rows = dart_quarterly.load(corp.corp_code, fs_div, limit=quarters)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{corp.corp_name}' 의 분기보고서를 찾지 못했습니다.\n"
                "신규 상장이라 아직 분기보고서가 없는 회사일 수 있습니다."
            ),
        )

    points = [_as_dict(r) for r in rows]

    # 4분기를 끼워 넣는다. 연결/별도 기준이 서로 다르면 섞지 않는다 — 다른 숫자다.
    if annual_div == fs_div:
        by_period = {(p["fiscal_year"], p["quarter"]): p for p in points}
        for annual in dart_financials.load(corp.corp_code, fs_div, years=6):
            if (annual.fiscal_year, 4) in by_period:
                continue
            made = _q4_from_annual(annual, by_period.get((annual.fiscal_year, 3)))
            if made is not None:
                points.append(made)

    points.sort(key=lambda p: (p["fiscal_year"], p["quarter"]))

    # 전년 동분기를 짚어 증가율을 낸다. **자르기 전** 목록에서 찾는다 — 화면에 안 보이는
    # 분기도 비교 대상으로는 쓸 수 있어야 맨 앞 분기에도 증가율이 나온다.
    lookup = {(p["fiscal_year"], p["quarter"]): p for p in points}
    points = points[-quarters:]

    return QuarterlyOut(
        stock_code=symbol,
        corp_name=corp.corp_name,
        corp_code=corp.corp_code,
        fs_div=fs_div,
        fs_label=FS_LABEL.get(fs_div, fs_div),
        currency=points[-1]["currency"],
        quarters=[
            _to_quarter(p, lookup.get((p["fiscal_year"] - 1, p["quarter"]))) for p in points
        ],
    )


# ====================================================================== 밸류에이션


class ValuationOut(BaseModel):
    """PER · PBR · 배당수익률. 값마다 무엇으로 냈는지가 함께 온다."""

    stock_code: str
    corp_name: str

    price: int = Field(description="계산에 쓴 주가 (원)")
    price_label: str = Field(description="실시간인지 확정 종가인지. 기준일이 다르다")
    listed_shares: int = Field(description="상장주식수 (보통주). KRX 기준")
    market_cap: int = Field(description="주가 × 상장주식수 (원)")

    fiscal_year: int | None = Field(description="PER·PBR 의 근거가 된 회계연도")
    fs_label: str | None = Field(description="연결 / 별도")
    owners_basis: bool = Field(
        description="지배주주 몫으로 계산했는가. 별도재무제표에는 비지배지분이 없어 거짓이다"
    )

    eps: int | None = Field(description="주당순이익 (원) = 지배주주순이익 / 상장주식수")
    bps: int | None = Field(description="주당순자산 (원) = 지배주주자본 / 상장주식수")
    dps: int | None = Field(description="주당 현금배당금 (원)")
    dps_year: int | None = Field(description="그 배당이 어느 회계연도 것인지")

    per: Decimal | None
    pbr: Decimal | None
    dividend_yield: Decimal | None = Field(description="주당배당금 / 현재가 (%)")

    per_note: str | None = Field(description="PER 을 내지 못한 사정")
    pbr_note: str | None = Field(description="PBR 을 내지 못한 사정")
    dividend_note: str | None = Field(description="배당수익률을 내지 못한 사정")


@router.get("/{symbol}/valuation", summary="밸류에이션 (PER·PBR·배당수익률)")
async def get_valuation(
    symbol: str = Path(description="단축코드 6자리 (예: 005930)", pattern=r"^\d{6}$"),
) -> ValuationOut:
    """**모든 값을 원자료에서 그때그때 계산한다.** 저장하지 않는다 — 주가가 계속 바뀌므로
    저장하는 순간 낡은 값이 된다.

    분모는 **지배주주 몫**을 쓴다. 연결 순이익·자본에는 비지배지분이 섞여 있어 그대로
    나누면 주주가 가진 값어치와 다른 숫자가 나온다(판단 근거는 `services/valuation.py`
    첫머리 참고).

    처음 조회하는 종목은 OpenDART 를 몇 번 부르느라 몇 초 걸린다.
    """
    corp = dart_corps.get_corp(symbol)
    if corp is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{symbol}' 의 DART 고유번호를 찾지 못했습니다.\n"
                "우선주나 비상장 종목은 재무 자료가 없어 밸류에이션을 낼 수 없습니다."
            ),
        )

    try:
        fs_div, _ = await dart_financials.ensure_financials(corp.corp_code, years=2)
        # 배당은 재무와 같은 회계연도를 본다. 최근 두 해를 채워 두면 결산 직후처럼
        # 최신 해가 아직 없을 때도 직전 해로 보여줄 수 있다.
        latest_year = dart_financials.latest_annual_year()
        await dividends_service.ensure_dividends(corp.corp_code, [latest_year, latest_year - 1])
    except DartError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = valuation_service.compute(
        symbol, corp.corp_code, fs_div, FS_LABEL.get(fs_div, fs_div)
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{corp.corp_name}' 의 주가나 상장주식수를 찾지 못했습니다.\n"
                "KRX 확정 시세가 아직 수집되지 않은 종목일 수 있습니다."
            ),
        )

    return ValuationOut(stock_code=symbol, corp_name=corp.corp_name, **vars(result))
