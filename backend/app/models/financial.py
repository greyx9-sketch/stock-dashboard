"""연간 재무 요약 테이블.

OpenDART 의 XBRL 재무제표에서 뽑아낸 연도별 핵심 수치를 담는다.

**여기 있는 값은 전부 XBRL 계정에서 그대로 가져온 것이다.** 마진·성장률처럼 파생되는 값은
저장하지 않고 조회할 때 이 원값으로 계산한다. 원값과 계산값이 따로 저장되면 나중에
서로 어긋나고, 어느 쪽이 맞는지 알 수 없게 된다(CLAUDE.md 절대 규칙 3).

금액은 정수(원)다. 조 단위라 크지만 BigInteger 범위(약 922경) 안에 넉넉히 들어간다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DartFinancial(Base):
    """한 회사의 한 회계연도 재무 요약."""

    __tablename__ = "dart_financials"

    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 연결(CFS)과 별도(OFS)는 다른 숫자다. 섞이면 안 되므로 기본키에 포함한다.
    fs_div: Mapped[str] = mapped_column(String(3), primary_key=True)

    # 손익계산서. 회사에 따라 없을 수 있다 —
    # 금융지주는 매출액 계정 자체를 쓰지 않는다(KB금융에 ifrs-full_Revenue 가 없다).
    revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 매출액/영업수익
    gross_profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 매출총이익
    operating_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 영업이익
    net_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 당기순이익

    # 재무상태표
    total_assets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_liabilities: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_equity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    currency: Mapped[str] = mapped_column(String(5), default="KRW")
    # 어느 보고서에서 나온 값인지. 숫자가 이상할 때 원문을 바로 열어 볼 수 있어야 한다.
    receipt_no: Mapped[str] = mapped_column(String(20), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (Index("ix_dart_financials_corp_year", "corp_code", "fiscal_year"),)

    def __repr__(self) -> str:
        return f"<DartFinancial {self.corp_code} {self.fiscal_year} {self.fs_div}>"
