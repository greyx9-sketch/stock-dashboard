"""배당 정보 테이블.

재무(`financial.py`)와 표를 나눈 이유: 배당은 **연결/별도 구분이 없다.** 회사가 한 해에
주당 얼마를 줬는지는 재무제표 작성 기준과 무관하다. 재무 표의 기본키에는 `fs_div` 가
들어 있어서, 같은 배당을 CFS·OFS 두 줄에 똑같이 복사하게 된다.

값은 OpenDART "배당에 관한 사항"(`/api/alotMatter.json`)에서 그대로 가져온다. 응답이
`se`(구분) 문자열로 항목을 나누는 표 형태라, 필요한 줄만 골라 칸으로 옮겨 담는다.

**보통주와 우선주를 따로 담는다.** 응답의 `stock_knd` 가 그 둘을 가르는데, 배당금이
다르다(삼성전자 2025: 보통주 1,668원 · 우선주 1,669원). 한쪽만 담으면 우선주 종목에
틀린 배당수익률이 붙는다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DartDividend(Base):
    """한 회사의 한 회계연도 배당."""

    __tablename__ = "dart_dividends"

    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 주당 현금배당금(원). 배당을 하지 않은 해는 비어 있다 — 0 이 아니라 없는 값이다.
    dps_common: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dps_preferred: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 현금배당금 총액(원). DART 는 백만원 단위로 주므로 넣을 때 원으로 바꾼다.
    total_cash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # DART 가 함께 알려주는 현금배당수익률(%). **그 해 결산일 기준이라 지금 주가와
    # 다르다.** 화면에 쓰는 배당수익률은 현재가로 우리가 따로 계산한다. 이 값은
    # 대조용으로만 들고 있는다.
    reported_yield: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)

    # 결산일. 배당 기준일과는 다르지만, 어느 회계연도 배당인지 밝히는 데 쓴다.
    settlement_date: Mapped[str | None] = mapped_column(String(10), nullable=True)

    receipt_no: Mapped[str] = mapped_column(String(20), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<DartDividend {self.corp_code} {self.fiscal_year} {self.dps_common}>"
