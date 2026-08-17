"""관심종목 테이블.

기획서 5.1 의 관심종목 그리드가 읽는 목록이다. 국내와 미국을 **한 목록에 섞어** 담는다.
실무에서 보는 단위가 "내가 보는 종목들"이고 시장별로 나뉘어 있지 않기 때문이다.

**브라우저 저장소를 쓰지 않는다**(절대 규칙 6). 그래서 이 목록은 서버 DB 에 있다.
사용자가 하나뿐이라 소유자 열을 두지 않았다 — 사이트 전체에 목록이 하나다.

`group_name` 은 기획서의 스키마를 따라 두었다. 화면은 아직 그룹을 나누지 않고 전부
`기본` 에 담는다. SQLite 는 나중에 열을 추가하기가 번거로워서, 쓸 것이 분명한 열은
지금 만들어 두는 편이 낫다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WatchlistItem(Base):
    """관심종목 한 줄."""

    __tablename__ = "watchlist"

    # 종목코드(국내 6자리) 또는 티커(미국). 같은 종목을 두 번 담을 수 없게 기본키로 둔다.
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)

    market: Mapped[str] = mapped_column(String(2))  # KR / US

    # 이름을 여기 함께 저장한다(비정규화).
    #
    # 이름의 출처가 시장마다 다르다 — 국내는 KRX 시세 테이블, 미국은 sec_companies 다.
    # 목록을 읽을 때마다 시장별로 갈라 조회하면 코드가 지저분해지고, 아직 시세를 받아
    # 본 적 없는 종목은 이름이 비어 버린다. 담는 시점에 한 번 정해 두면 읽기가 단순하다.
    #
    # 회사가 이름을 바꾸면 이 값은 낡는다. 담을 때 토스에서 받은 이름이므로 흔한 일은
    # 아니고, 지웠다 다시 담으면 갱신된다.
    name: Mapped[str] = mapped_column(String(80))

    group_name: Mapped[str] = mapped_column(String(40), default="기본")

    # 화면에 보여줄 순서. 위/아래로 옮길 때 이 값을 맞바꾼다.
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
