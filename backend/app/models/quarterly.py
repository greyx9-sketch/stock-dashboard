"""분기 재무 요약 테이블.

연간(`financial.py`)과 **테이블을 나눈다.** 같은 표에 넣고 `quarter` 칸을 0/1/2/3/4 로
쓰는 방법도 있지만, 분기에만 있는 개념(누적)과 연간에만 있는 개념이 섞여 절반이 늘
비어 있는 표가 된다. 무엇보다 이미 잘 돌고 있는 연간 표의 기본키를 바꾸는 일이라
위험 대비 얻는 것이 없다.

## 무엇을 저장하고 무엇을 저장하지 않는가

**저장하는 것은 DART 가 준 원값뿐이다.** 분기 보고서의 손익 줄은 두 금액을 나란히 들고
온다 — `thstrm_amount`(당분기 3개월)와 `thstrm_add_amount`(연초부터의 누적). 둘 다
보고서에 실제로 적힌 숫자이므로 둘 다 그대로 담는다. 누적을 분기값 합으로 만들어 쓰지
않는 이유는, 뒤 보고서에서 재작성되면 합과 공시된 누적이 어긋나기 때문이다. 그때는
**공시된 쪽이 맞다.**

**4분기 행은 여기 없다.** DART 에 4분기 보고서라는 것이 없어서다(연간 사업보고서가
그 자리를 대신한다). 4분기 손익은 `연간 − 3분기 누적`으로만 구할 수 있는 계산값이라
저장하지 않고 조회할 때 만든다(`routers/financials.py`). 계산값을 저장하면 나중에 연간
원값이 재작성됐을 때 둘이 어긋나고, 어느 쪽이 맞는지 알 수 없게 된다 — 연간 표가
파생값을 저장하지 않는 것과 같은 이유다.

## 재무상태표에는 누적이 없다

자산·부채·자본은 **그 시점의 잔액**이라 "3개월치"라는 개념이 성립하지 않는다. 그래서
누적 칸을 따로 두지 않고 분기말 잔액 하나만 담는다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DartQuarterly(Base):
    """한 회사의 한 분기 재무 요약."""

    __tablename__ = "dart_quarterly"

    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 1·2·3 만 들어온다. 4 는 계산값이라 저장하지 않는다(파일 첫머리 참고).
    quarter: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 연결(CFS)과 별도(OFS)는 다른 숫자다. 섞이면 안 되므로 기본키에 포함한다.
    fs_div: Mapped[str] = mapped_column(String(3), primary_key=True)

    # ---------------------------------------------------------------- 손익: 당분기 3개월
    #
    # 조사한 9개 회사(제조·인터넷·바이오·유틸리티·금융지주)가 **전부** 3개월치를 준다.
    # 없는 항목은 계정 자체가 없는 경우다 — 금융지주에는 매출액 계정이 없다.
    revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    gross_profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operating_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # ---------------------------------------------------------------- 손익: 연초부터 누적
    revenue_cum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    gross_profit_cum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operating_income_cum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_income_cum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # ---------------------------------------------------------------- 재무상태: 분기말 잔액
    total_assets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_liabilities: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_equity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    currency: Mapped[str] = mapped_column(String(5), default="KRW")
    # 어느 보고서에서 나온 값인지. 숫자가 이상할 때 원문을 바로 열어 볼 수 있어야 한다.
    receipt_no: Mapped[str] = mapped_column(String(20), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_dart_quarterly_corp_period", "corp_code", "fiscal_year", "quarter"),
    )

    def __repr__(self) -> str:
        return f"<DartQuarterly {self.corp_code} {self.fiscal_year}Q{self.quarter} {self.fs_div}>"
