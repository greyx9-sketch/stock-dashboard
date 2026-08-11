"""미국 상장사 매핑과 연간 재무 테이블.

SEC 는 티커가 아니라 CIK(제출자 고유번호)로 조회한다. 그 매핑과, XBRL 에서 뽑아낸
연도별 핵심 수치를 담는다.

국내(DART)와 표를 나눈 이유: 회계 기준이 다르고(IFRS vs US-GAAP), 통화가 다르고,
회계연도 개념이 다르다(미국은 12월 결산이 아닌 회사가 흔하다). 한 표에 억지로 합치면
어느 쪽 규칙으로 읽어야 하는지 알 수 없는 행이 생긴다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SecCompany(Base):
    """티커 ↔ CIK 매핑."""

    __tablename__ = "sec_companies"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    cik: Mapped[str] = mapped_column(String(10))  # 10자리 zero-padding
    name: Mapped[str] = mapped_column(String(200))

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (Index("ix_sec_companies_cik", "cik"),)

    def __repr__(self) -> str:
        return f"<SecCompany {self.ticker} {self.name} (CIK {self.cik})>"


class SecFinancial(Base):
    """한 회사의 한 회계연도 재무 요약 (10-K 기준)."""

    __tablename__ = "sec_financials"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 미국 회사는 12월 결산이 아닌 경우가 흔하다(애플은 9월 말). 회계연도 숫자만으로는
    # 어느 기간인지 알 수 없으므로 실제 종료일을 함께 남긴다.
    period_end: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD

    revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    gross_profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operating_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_assets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_liabilities: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_equity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    currency: Mapped[str] = mapped_column(String(5), default="USD")
    # 이 값이 나온 보고서. 같은 연도가 여러 보고서에 나오므로 어느 것을 썼는지 남긴다.
    accession_no: Mapped[str] = mapped_column(String(25), default="")
    filed_date: Mapped[str] = mapped_column(String(10), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (Index("ix_sec_financials_cik_year", "cik", "fiscal_year"),)

    def __repr__(self) -> str:
        return f"<SecFinancial {self.cik} FY{self.fiscal_year}>"
