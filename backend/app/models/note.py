"""종목 메모 테이블.

기획서가 이 기능을 **"이 프로젝트의 차별점"** 이라고 적었다. 증권사 HTS 에는 없고,
텔레그램 채널에 흘려보내던 코멘트를 종목별로 쌓으면 시간이 지날수록 자산이 된다.

그래서 설계에서 지키는 것 두 가지:

  1. **지우기 어렵게 하지 않되, 사라지지 않게 한다.** 메모는 서버 DB 에 있고 매일
     백업된다(`backend/scripts/backup_db.py`). 브라우저에 저장하면 브라우저를 지우는
     순간 몇 년치가 함께 사라진다.
  2. **고친 흔적을 남긴다.** `created_at` 과 `updated_at` 을 따로 든다. 나중에 그 판단을
     언제 했는지가 메모의 값어치인데, 고친 시각이 작성 시각을 덮어쓰면 그게 사라진다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Note(Base):
    """종목 하나에 대한 메모 한 건."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 국내 6자리 코드 또는 미국 티커. 관심종목과 같은 표기를 쓴다(미국은 대문자).
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    market: Mapped[str] = mapped_column(String(2))  # KR / US

    body: Mapped[str] = mapped_column(Text)

    # 쉼표로 구분한 태그. 별도 테이블로 정규화하지 않는다 — 태그로 검색·집계할 계획이
    # 생기기 전까지는 표 하나가 다루기 쉽고, 옮기는 것도 어렵지 않다.
    tags: Mapped[str] = mapped_column(String(200), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # 종목 상세를 열 때마다 "이 종목의 메모를 최신순으로" 읽는다. 그 질의를 위한 색인이다.
    __table_args__ = (Index("ix_notes_symbol_created", "symbol", "created_at"),)
