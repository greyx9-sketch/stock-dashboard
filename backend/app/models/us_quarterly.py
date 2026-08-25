"""미국 분기 재무 테이블.

국내(`quarterly.py`)와 **담는 것이 같다.** 10-Q 도 손익을 3개월치와 연초부터 누적,
두 가지로 함께 싣고 재무상태표는 분기말 잔액 하나만 싣는다. 그래서 칸 구성이 같고,
화면도 국내와 같은 3개월/누적 전환을 쓴다.

다른 것은 **회계연도가 회사마다 다르다**는 점이다. 애플의 FY2026 1분기는 2025년 12월에
끝나고, 마이크로소프트의 FY2026 1분기는 2025년 9월에 끝난다. 그래서 분기말 날짜를
따로 담는다 — "2026 1Q" 라고만 적으면 그게 언제인지 알 수 없다.

**4분기 행은 여기 없다.** 미국도 4분기를 따로 내지 않고 10-K 가 그 자리를 대신한다.
`연간 − 3분기 누적`으로만 구할 수 있는 계산값이라 저장하지 않고 조회할 때 만든다
(국내와 같은 판단 — `models/quarterly.py` 첫머리 참고).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SecQuarterly(Base):
    """한 회사의 한 분기 재무 요약(10-Q)."""

    __tablename__ = "sec_quarterly"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 1·2·3 만 들어온다. 4 는 계산값이라 저장하지 않는다.
    quarter: Mapped[int] = mapped_column(Integer, primary_key=True)

    # **회계연도가 회사마다 달라 반드시 함께 담는다.** 애플 FY2026 1Q 는 2025-12-27 에
    # 끝난다 — 날짜가 없으면 "2026 1Q" 가 언제인지 알 수 없다.
    period_end: Mapped[str] = mapped_column(String(10), default="")

    # 손익: 당분기 3개월
    revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    gross_profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operating_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 손익: 회계연도 초부터 누적
    revenue_cum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    gross_profit_cum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operating_income_cum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_income_cum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 재무상태: 분기말 잔액. 누적이라는 개념이 없다.
    total_assets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_liabilities: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_equity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    currency: Mapped[str] = mapped_column(String(5), default="USD")
    accession_no: Mapped[str] = mapped_column(String(25), default="")
    filed_date: Mapped[str] = mapped_column(String(10), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (Index("ix_sec_quarterly_cik_period", "cik", "fiscal_year", "quarter"),)

    def __repr__(self) -> str:
        return f"<SecQuarterly {self.cik} FY{self.fiscal_year}Q{self.quarter}>"
