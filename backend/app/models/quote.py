"""KRX 확정 일별 시세 테이블.

공공데이터포털(금융위원회 주식시세정보)에서 받은 **정규장 확정 종가**를 그대로 쌓는다.
이 값이 등락률의 기준가이자 과거 차트의 근거가 된다.

금액과 수량은 전부 정수로 저장한다. 국내 주식의 원 단위 금액·주식 수는 소수가 없고,
정수로 두어야 정렬·합계가 정확하고 부동소수 오차가 끼어들 여지가 없다.
등락률만 소수점 두 자리라 Numeric 으로 둔다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KrxDailyQuote(Base):
    """한 종목의 하루치 확정 시세. (거래일, 종목코드) 조합이 유일하다."""

    __tablename__ = "krx_daily_quotes"

    # 거래일(YYYY-MM-DD)과 단축코드 6자리를 묶어 기본키로 쓴다.
    # 같은 날 같은 종목을 다시 받아도 덮어쓰기가 되도록 하기 위한 것이다.
    trade_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(6), primary_key=True)

    isin: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(80))
    market: Mapped[str] = mapped_column(String(10))  # KOSPI / KOSDAQ / KONEX

    close: Mapped[int] = mapped_column(BigInteger)  # 정규장 확정 종가 = 다음날 기준가
    change: Mapped[int] = mapped_column(BigInteger)  # 전일 대비
    change_rate: Mapped[float] = mapped_column(Numeric(8, 2))  # 등락률 (%)
    open: Mapped[int] = mapped_column(BigInteger)
    high: Mapped[int] = mapped_column(BigInteger)
    low: Mapped[int] = mapped_column(BigInteger)

    volume: Mapped[int] = mapped_column(BigInteger)  # 거래량 (주)
    trade_value: Mapped[int] = mapped_column(BigInteger)  # 거래대금 (원)
    listed_shares: Mapped[int] = mapped_column(BigInteger)  # 상장주식수
    market_cap: Mapped[int] = mapped_column(BigInteger)  # 시가총액 (원)

    # 언제 받아온 값인지. 데이터가 이상할 때 언제 적재분인지 추적하려고 남긴다.
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        # 종목 하나의 기간 조회(차트)가 가장 잦은 접근 패턴이다.
        Index("ix_krx_daily_quotes_symbol_date", "symbol", "trade_date"),
        # 특정 날짜의 전 종목 조회(랭킹·적재 여부 확인)가 그다음이다.
        Index("ix_krx_daily_quotes_date", "trade_date"),
    )

    def __repr__(self) -> str:
        return f"<KrxDailyQuote {self.symbol} {self.trade_date} 종가 {self.close:,}>"
