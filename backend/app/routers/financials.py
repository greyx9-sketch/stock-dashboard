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
from app.services import dart_corps, dart_financials

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
        roe=_pct(row.net_income, row.total_equity),
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
