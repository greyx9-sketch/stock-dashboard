"""일정 캘린더 엔드포인트.

화면은 **달 단위로** 묻는다. 월간 뷰 하나가 한 번의 요청으로 채워져야 달을 넘길 때
끊기지 않는다.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.models.event import KINDS
from app.services import events as events_service

router = APIRouter(prefix="/api/events", tags=["일정"])

# 화면이 새 일정을 만들 때 고를 수 있는 종류. 자동으로 만들어지는 종류(금통위·FOMC·만기)는
# 여기 없다 — 사람이 그 이름으로 직접 적어 넣으면 자동 일정과 구분이 안 된다.
CREATABLE_KINDS = KINDS


class EventOut(BaseModel):
    event_date: date
    kind: str = Field(description="금통위 · FOMC · 만기 · 실적 · 배당 · 공모주 · 기타")
    title: str
    editable: bool = Field(description="직접 입력한 것만 참. 자동 일정은 고칠 수 없다")
    id: int | None = Field(description="직접 입력한 일정의 번호. 지울 때 쓴다")
    symbol: str | None
    memo: str | None
    source: str | None = Field(description="이 일정이 어디서 왔는지")
    source_url: str | None


class MonthOut(BaseModel):
    year: int
    month: int
    events: list[EventOut] = Field(description="날짜순")


class NewEvent(BaseModel):
    event_date: date
    kind: str
    title: str = Field(min_length=1, max_length=200)
    symbol: str | None = Field(default=None, max_length=20)
    memo: str | None = Field(default=None, max_length=1000)


@router.get("/{year}/{month}", summary="한 달의 일정")
def get_month(
    year: int = Path(ge=2000, le=2100),
    month: int = Path(ge=1, le=12),
) -> MonthOut:
    """그 달에 걸린 일정 전부. 자동 일정과 직접 적은 것이 섞여 나온다."""
    begin, end = events_service.month_range(year, month)
    return MonthOut(
        year=year,
        month=month,
        events=[EventOut(**vars(e)) for e in events_service.load(begin, end)],
    )


class UpcomingOut(BaseModel):
    """다가오는 일정 한 건. 화면 위쪽 띠가 쓴다."""

    event: EventOut
    days_away: int = Field(description="오늘로부터 며칠 뒤인가. 오늘이면 0")


@router.get("/upcoming", summary="다가오는 일정")
def get_upcoming(
    days: int = Query(60, ge=1, le=365, description="오늘부터 며칠 앞까지 볼 것인가"),
    limit: int = Query(4, ge=1, le=20),
) -> list[UpcomingOut]:
    """오늘 이후로 가장 가까운 일정들. **오늘 것도 넣는다** — 오늘이 금통위인데 목록에서
    빠지면 그날 아침에 가장 필요한 정보가 사라진다.

    `days_away` 를 함께 준다. 화면이 "D-2" 를 만들 때 날짜 계산을 다시 하지 않도록,
    그리고 서버와 브라우저의 오늘이 어긋나지 않도록 여기서 낸다 — 시간대가 다르면
    하루 어긋난다.
    """
    today = date.today()
    end = date.fromordinal(today.toordinal() + days)
    found = events_service.load(today, end)[:limit]
    return [
        UpcomingOut(
            event=EventOut(**vars(item)),
            days_away=(item.event_date - today).days,
        )
        for item in found
    ]


@router.post("", summary="일정 추가", status_code=201)
def create_event(payload: NewEvent) -> EventOut:
    if payload.kind not in CREATABLE_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"종류는 {', '.join(CREATABLE_KINDS)} 중 하나여야 합니다.",
        )
    new_id = events_service.add(
        event_date=payload.event_date,
        kind=payload.kind,
        title=payload.title,
        symbol=payload.symbol,
        memo=payload.memo,
    )
    return EventOut(
        event_date=payload.event_date,
        kind=payload.kind,
        title=payload.title.strip(),
        editable=True,
        id=new_id,
        symbol=(payload.symbol or "").strip() or None,
        memo=(payload.memo or "").strip() or None,
        source="직접 입력",
        source_url=None,
    )


@router.delete("/{event_id}", summary="일정 삭제")
def delete_event(event_id: int = Path(ge=1)) -> dict[str, bool]:
    """지운 뒤 `{"removed": true}` 를 돌려준다.

    204(본문 없음)를 쓰지 않는 이유: 화면의 공통 요청 함수가 응답을 항상 JSON 으로
    읽는다. 메모 삭제도 같은 방식이라 둘을 맞춰 둔다.
    """
    if not events_service.remove(event_id):
        raise HTTPException(status_code=404, detail="그 일정을 찾지 못했습니다.")
    return {"removed": True}
