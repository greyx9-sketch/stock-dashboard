"""미국 상장사 매핑과 연간 재무 테이블.

SEC 는 티커가 아니라 CIK(제출자 고유번호)로 조회한다. 그 매핑과, XBRL 에서 뽑아낸
연도별 핵심 수치를 담는다.

국내(DART)와 표를 나눈 이유: 회계 기준이 다르고(IFRS vs US-GAAP), 통화가 다르고,
회계연도 개념이 다르다(미국은 12월 결산이 아닌 회사가 흔하다). 한 표에 억지로 합치면
어느 쪽 규칙으로 읽어야 하는지 알 수 없는 행이 생긴다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SecCompany(Base):
    """티커 ↔ CIK 매핑."""

    __tablename__ = "sec_companies"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    cik: Mapped[str] = mapped_column(String(10))  # 10자리 zero-padding
    name: Mapped[str] = mapped_column(String(200))

    # 발행주식수(`dei:EntityCommonStockSharesOutstanding`). **회계연도별 값이 아니라
    # 가장 최근 제출 서류 표지에 적힌 현재 수량**이라 회사 쪽에 둔다.
    # 언제 기준인지 함께 담는다 — 시가총액을 이 값으로 내므로 시점이 중요하다.
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    shares_as_of: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # SEC 표준산업분류(SIC). 동종업계 비교의 묶는 기준이다.
    #
    # **국내(DART)보다 다루기 쉽다.** 네 자리로 길이가 일정하고 이름까지 함께 온다
    # (`sicDescription`). 그래서 국내처럼 앞자리를 잘라 묶을 필요가 없고, 화면에
    # "Semiconductors & Related Devices" 라고 그대로 적을 수 있다.
    sic: Mapped[str | None] = mapped_column(String(6), nullable=True)
    sic_description: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # 마지막으로 받아 둔 주가와 그 시각.
    #
    # **국내의 KRX 확정 종가에 해당하는 자리다.** 스크리너는 후보 전부의 시가총액을
    # 알아야 PER 을 낼 수 있는데, 그때마다 실시간 폴러에 유니버스를 통째로 등록하면
    # 웹소켓 구독 한도(100종목)를 스크리너가 먹어 치워 사용자가 보던 종목이 실시간에서
    # 밀려난다. 그래서 값을 미리 받아 여기 두고, 스크리너는 DB 만 읽는다.
    #
    # 시각을 함께 담는 이유 — 미국은 확정 종가라는 개념이 없어 "언제 값인지"를
    # 화면이 밝혀야 한다. 장중에 받은 값과 마감 뒤에 받은 값이 다른 뜻이기 때문이다.
    last_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    # 이 **티커 하나**의 상장주식수(토스 기준). 위 `shares_outstanding` 은 SEC 가
    # 회사(CIK) 단위로 보고한 수라 둘은 다른 것을 센다.
    #
    # 왜 두는가 — 한 회사가 티커 여러 개로 상장돼 있을 때 어느 것이 보통주인지
    # 가리는 데 쓴다. 티커 글자만으로는 알 수 없다(`us_universe.screen_universe`).
    # 컴캐스트는 우선주 CCZ 가 258만주, 본주 CMCSA 가 35억주다.
    listed_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 이 티커의 증권 이름(토스 기준). 보통주인지 우선주·채권인지 가리는 데 쓴다.
    # SEC 자료에는 증권 종류를 알려 주는 항목이 없다.
    listed_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_close_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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

    # 주당 현금배당금(달러). 그 회계연도에 선언된 값이다.
    # **분기치를 잘못 집지 않도록** 기간이 1년인 것만 쓴다(`services/sec_financials.py`).
    dps: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

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
