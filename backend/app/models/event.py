"""사용자가 직접 적어 넣는 일정.

**자동으로 구할 수 있는 일정은 여기 저장하지 않는다.** 금통위·FOMC 는 연 단위로 공표된
값이라 `app/data/policy_meetings.json` 에 적혀 있고, 옵션 만기는 규칙으로 계산된다
(`services/events.py`). 그것들을 DB 에 복사해 두면 원본을 고쳤을 때 둘이 어긋난다 —
재무표가 파생값을 저장하지 않는 것과 같은 이유다.

여기 담기는 것은 **사람만 아는 일정**이다. 실적발표 예정일, 배당 기준일, 공모주 청약일
같은 것들. 기획서 3.6 이 짚었듯 이것들은 하나의 API 로 깔끔하게 오지 않는다:

> 1단계에서는 수기 입력 + 캘린더 UI만 만들고, 자동 수집은 2단계로 미루는 것을 권한다.
> 여기서 완벽을 추구하면 프로젝트가 여기서 멈춘다.

**메모와 함께 이 사이트에서 복구할 수 없는 데이터다.** 시세·재무·공시는 언제든 다시
받아 올 수 있지만 직접 적은 일정은 그렇지 않다. 매일 06:20 백업에 함께 들어간다.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 일정 종류. 화면에서 색을 나누는 기준이라 늘릴 때는 색도 함께 정해야 한다.
KINDS = ("실적", "배당", "공모주", "기타")


class UserEvent(Base):
    """직접 적어 넣은 일정 하나."""

    __tablename__ = "user_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 날짜만 담는다. 시각까지 관리하면 시간대 문제가 따라오는데, 이 캘린더는 월간 뷰라
    # 시각을 보여줄 자리가 없다. 필요하면 제목에 적는다.
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # 종목과 이어 두면 캘린더에서 종목 상세로 건너갈 수 있다. 없어도 된다 —
    # "FOMC 다음날 대응" 처럼 종목과 무관한 일정도 적을 수 있어야 한다.
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)

    memo: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (Index("ix_user_events_date", "event_date"),)

    def __repr__(self) -> str:
        return f"<UserEvent {self.event_date} {self.kind} {self.title[:20]}>"
