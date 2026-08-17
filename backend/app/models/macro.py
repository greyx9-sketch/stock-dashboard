"""매크로 지표의 마지막 성공값.

**시계열 저장소가 아니다.** 지표별로 딱 한 행, 가장 최근 성공값만 담는다.
과거 추이는 `시황` 프로젝트가 이미 관리하고 있어 여기서 또 쌓을 이유가 없다.

용도는 하나다 — 외부에서 값을 못 받았을 때 화면이 비지 않게 하는 버팀목. 스트립이
통째로 비면 사이트가 고장 난 것처럼 보이는데, 실제로는 지표 하나가 안 온 것뿐인
경우가 대부분이다. 이 표에서 꺼내 보여주고 "갱신 지연" 으로 표시한다.

값을 문자열로 저장하는 이유: 화면에 쓸 표기(반올림 자리수, 천단위 쉼표)가 지표마다
다르고 그 판단이 서비스 계층에 있다. 숫자로 저장하면 꺼낼 때 그 판단을 또 해야 한다.
계산에 쓰는 값이 아니라 **보여줄 값**이라 문자열이 맞다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MacroValue(Base):
    """지표 하나의 마지막 성공값."""

    __tablename__ = "macro_values"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    label: Mapped[str] = mapped_column(String(60), default="")
    value: Mapped[str] = mapped_column(String(40), default="")
    unit: Mapped[str] = mapped_column(String(10), default="")
    change_rate: Mapped[str] = mapped_column(String(20), default="")
    as_of: Mapped[str] = mapped_column(String(40), default="")
    source: Mapped[str] = mapped_column(String(60), default="")
    note: Mapped[str] = mapped_column(String(200), default="")

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<MacroValue {self.code}={self.value}{self.unit}>"
