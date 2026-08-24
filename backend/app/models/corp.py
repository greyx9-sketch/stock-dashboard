"""DART 고유번호 매핑 테이블.

OpenDART 는 종목코드로 조회할 수 없고 자체 고유번호(corp_code)를 쓴다. 그 매핑을
한 번 받아 두고 쓰기 위한 표다.

전체 매핑을 받는 호출은 3.5MB ZIP 을 내려받는 무거운 작업이고, 매핑 자체는 신규 상장·
상호 변경이 있을 때만 바뀐다. 그래서 조회할 때마다 받지 않고 여기에 넣어 두고 주기적으로만
갱신한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DartCorp(Base):
    """상장사 하나의 종목코드 ↔ DART 고유번호 매핑."""

    __tablename__ = "dart_corps"

    # 이 프로젝트는 항상 종목코드에서 출발하므로 그것을 기본키로 둔다.
    stock_code: Mapped[str] = mapped_column(String(6), primary_key=True)

    corp_code: Mapped[str] = mapped_column(String(8))  # DART 고유번호 8자리
    corp_name: Mapped[str] = mapped_column(String(120))
    modify_date: Mapped[str] = mapped_column(String(8))  # DART 가 알려주는 최종 변경일

    # 표준산업분류 코드(DART 기업개황의 `induty_code`). 동종업계 비교의 묶는 기준이다.
    #
    # **이름 대신 코드로 묶는다.** 코드→업종명 대응표를 우리가 갖고 있지 않아서인데,
    # 비교 자체에는 이름이 필요 없다 — 같은 코드끼리 모아 놓고 회사 이름을 보여주면
    # 사람이 읽을 수 있다. 지어낸 업종명을 붙이느니 코드를 그대로 밝힌다.
    induty_code: Mapped[str | None] = mapped_column(String(10), nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        # 공시 응답에는 corp_code 만 들어 있어 역방향 조회가 필요할 때가 있다.
        Index("ix_dart_corps_corp_code", "corp_code"),
    )

    def __repr__(self) -> str:
        return f"<DartCorp {self.stock_code} {self.corp_name} ({self.corp_code})>"
