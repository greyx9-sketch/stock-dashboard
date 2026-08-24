"""캘린더에 올라갈 일정을 모은다.

일정은 **세 갈래**로 들어오고, 각각 믿을 수 있는 근거가 다르다.

| 갈래 | 어디서 | 근거 |
| --- | --- | --- |
| 금통위·FOMC | `app/data/policy_meetings.json` | 두 중앙은행이 연 단위로 공표한 원문 |
| 옵션 만기 | 여기서 계산 | KRX 규칙 — 각 결제월의 두 번째 목요일 |
| 그 밖의 일정 | 사용자가 직접 입력 (`models/event.py`) | 사람 |

**앞의 둘은 DB 에 저장하지 않는다.** 원문 파일과 규칙에서 매번 만들어 낸다. 복사해 두면
원본을 고쳤을 때 둘이 어긋나고, 어느 쪽이 맞는지 알 수 없게 된다.

## 왜 실적발표·배당 기준일을 자동으로 안 채우는가

기획서 3.6 이 이 부분을 "가장 까다로운 부분"이라 부르며 이렇게 적었다:

> 1단계에서는 수기 입력 + 캘린더 UI만 만들고, 자동 수집은 2단계로 미루는 것을 권한다.
> 여기서 완벽을 추구하면 프로젝트가 여기서 멈춘다.

실제로 그렇다. DART 공시 목록으로는 **이미 지나간 일**만 알 수 있다 — 배당 기준일을
알려면 공시 본문을 열어 파싱해야 하고, 실적발표 예정일은 회사가 따로 예고했을 때만
있다. 그 절반짜리 자동화를 붙이면 "캘린더에 없으니 없는 일정"이라고 잘못 믿게 된다.
**빈 것이 틀린 것보다 낫다.**
"""

from __future__ import annotations

import json
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select

from app.models.base import get_session
from app.models.event import UserEvent

SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "policy_meetings.json"

# KRX 파생상품 최종거래일 규칙(2026-08-24 KRX 원문 확인): 각 결제월의 두 번째 목요일.
# date.weekday() 에서 목요일은 3 이다.
THURSDAY = 3
SECOND_WEEK = 2


@dataclass(frozen=True)
class CalendarEvent:
    """캘린더에 찍히는 일정 하나. 어디서 왔는지를 반드시 들고 다닌다."""

    event_date: date
    kind: str
    title: str
    # 사람이 고칠 수 있는 것인가. 자동으로 만든 일정은 지우거나 고칠 수 없다.
    editable: bool
    id: int | None = None
    symbol: str | None = None
    memo: str | None = None
    # 이 값이 어디서 왔는지. 화면 아래에 그대로 밝힌다.
    source: str | None = None
    source_url: str | None = None


@lru_cache(maxsize=1)
def _seed() -> dict:
    """공표된 회의 일정. 파일이 바뀌는 일이 거의 없어 한 번만 읽는다."""
    with SEED_PATH.open(encoding="utf-8") as fp:
        return json.load(fp)


def option_expiry(year: int, month: int) -> date:
    """그 달의 옵션·선물 만기일 — **두 번째 목요일**.

    **휴장일이면 앞 영업일로 당겨진다.** 그 보정은 하지 않는다. 미래 휴장일표를 우리가
    들고 있지 않아서인데, 지어내느니 규칙대로 찍고 화면에 그 사실을 밝힌다.
    """
    first_weekday, _ = monthrange(year, month)
    # 1일의 요일에서 첫 목요일까지 며칠 걸리는지 센다.
    days_to_first = (THURSDAY - first_weekday) % 7
    return date(year, month, 1 + days_to_first + 7 * (SECOND_WEEK - 1))


def _policy_events(begin: date, end: date) -> list[CalendarEvent]:
    """금통위·FOMC. 원문에서 옮겨 적은 값을 그대로 쓴다."""
    seed = _seed()
    sources = seed["출처"]
    out: list[CalendarEvent] = []

    for item in seed["금통위"]:
        when = date.fromisoformat(item["date"])
        if begin <= when <= end:
            out.append(
                CalendarEvent(
                    event_date=when,
                    kind="금통위",
                    title="한국은행 금통위 (통화정책방향)",
                    editable=False,
                    source=f"한국은행 공표 · {seed['확인일']} 확인",
                    source_url=sources["금통위"],
                )
            )

    for item in seed["FOMC"]:
        when = date.fromisoformat(item["date"])
        if not (begin <= when <= end):
            continue
        # 회의 둘째 날 미국 동부 오후에 발표된다 → 한국시간으로는 다음날 새벽이다.
        # 날짜를 옮기지 않고 제목에 밝힌다. 옮기면 원문과 대조할 때 헷갈린다.
        extra = " · 경제전망(SEP) 공개" if item["sep"] else ""
        out.append(
            CalendarEvent(
                event_date=when,
                kind="FOMC",
                title=f"FOMC 결정{extra}",
                editable=False,
                memo="미국 동부 오후 발표 — 한국시간으로는 다음날 새벽입니다.",
                source=f"연준 공표 · {seed['확인일']} 확인",
                source_url=sources["FOMC"],
            )
        )
    return out


def _expiry_events(begin: date, end: date) -> list[CalendarEvent]:
    """옵션 만기. 달마다 하나씩 계산해 넣는다."""
    out: list[CalendarEvent] = []
    year, month = begin.year, begin.month
    while (year, month) <= (end.year, end.month):
        when = option_expiry(year, month)
        if begin <= when <= end:
            out.append(
                CalendarEvent(
                    event_date=when,
                    kind="만기",
                    title="지수 선물·옵션 만기",
                    editable=False,
                    memo="휴장일이면 앞 영업일로 당겨집니다. 그 보정은 반영돼 있지 않습니다.",
                    source="KRX 규칙 — 각 결제월의 두 번째 목요일",
                    source_url="https://open.krx.co.kr/contents/OPN/01/01050101/OPN01050101.jsp",
                )
            )
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def _user_events(begin: date, end: date) -> list[CalendarEvent]:
    with get_session() as session:
        rows = session.execute(
            select(UserEvent)
            .where(UserEvent.event_date >= begin)
            .where(UserEvent.event_date <= end)
            .order_by(UserEvent.event_date)
        ).scalars()
        return [
            CalendarEvent(
                event_date=row.event_date,
                kind=row.kind,
                title=row.title,
                editable=True,
                id=row.id,
                symbol=row.symbol,
                memo=row.memo,
                source="직접 입력",
            )
            for row in rows
        ]


def load(begin: date, end: date) -> list[CalendarEvent]:
    """그 기간의 일정 전부. **날짜순으로** 돌려준다."""
    events = _policy_events(begin, end) + _expiry_events(begin, end) + _user_events(begin, end)
    # 같은 날에는 자동 일정을 먼저, 직접 입력한 것을 뒤에 둔다. 직접 적은 것이
    # 더 아래에 모여 있어야 찾기 쉽다.
    events.sort(key=lambda e: (e.event_date, e.editable, e.kind))
    return events


def add(*, event_date: date, kind: str, title: str, symbol: str | None, memo: str | None) -> int:
    with get_session() as session:
        row = UserEvent(
            event_date=event_date,
            kind=kind,
            title=title.strip(),
            symbol=(symbol or "").strip() or None,
            memo=(memo or "").strip() or None,
        )
        session.add(row)
        session.commit()
        return row.id


def remove(event_id: int) -> bool:
    """지웠으면 참. 이미 없으면 거짓 — 두 번 눌러도 오류로 만들지 않는다."""
    with get_session() as session:
        row = session.get(UserEvent, event_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def month_range(year: int, month: int) -> tuple[date, date]:
    """그 달의 첫날과 마지막날. 화면이 달 단위로 묻기 때문에 여기서 만들어 준다."""
    _, last = monthrange(year, month)
    return date(year, month, 1), date(year, month, last)
