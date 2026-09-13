"""종목 메모 엔드포인트.

기획서가 **"이 프로젝트의 차별점"** 이라 부른 기능이다. 증권사 HTS 에는 없다.

관심종목과 마찬가지로 화면이 서버 상태를 바꾸는 경로다. 읽기 전용 대시보드라는 원칙과
어긋나 보이지만, 메모는 사용자 자신이 쓴 글이고 매매·계좌와는 무관하다.

브라우저 저장소를 쓰지 않으므로(절대 규칙 6) 메모는 서버 DB 에 있다. 그래서 매일 백업에
함께 들어가고, 브라우저를 지워도 사라지지 않는다.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.services import note_return, notes as service

router = APIRouter(prefix="/api/notes", tags=["종목 메모"])


class NoteBody(BaseModel):
    body: str = Field(description="메모 본문", min_length=1, max_length=service.MAX_BODY)
    tags: list[str] = Field(default_factory=list, description="태그 목록. # 는 붙이지 않아도 된다")


class NoteIn(NoteBody):
    symbol: str = Field(description="국내 6자리 종목코드 또는 미국 티커", min_length=1, max_length=20)


class NoteResponse(BaseModel):
    id: int
    symbol: str
    market: str = Field(description="KR / US")
    body: str
    tags: list[str]
    created_at: str = Field(description="작성 시각 (UTC 오프셋 포함)")
    updated_at: str
    edited: bool = Field(description="작성 뒤에 고친 적이 있는가")


def _out(note: service.NoteOut) -> NoteResponse:
    return NoteResponse(**vars(note))


@router.get("", summary="메모 목록")
def list_notes(
    symbol: str | None = Query(None, description="종목 코드. 없으면 전체에서 최근 것부터"),
    limit: int = Query(50, ge=1, le=service.MAX_LIMIT),
) -> list[NoteResponse]:
    """최신순으로 돌려준다."""
    return [_out(n) for n in service.list_notes(symbol, limit=limit)]


class NoteReturnOut(BaseModel):
    """메모 한 건의 회고."""

    note_id: int
    symbol: str
    base_date: str = Field(description="기준 거래일. 메모를 쓴 날, 휴장이면 직전 거래일")
    base_close: Decimal
    as_of: str = Field(description="비교 대상 거래일")
    last_close: Decimal
    change_rate: float = Field(description="그 사이 등락률 (%)")
    days: int = Field(description="두 거래일 사이의 달력 일수")
    index_label: str | None = Field(description="견준 지수 이름. 코스피 / 코스닥 / S&P500")
    index_rate: float | None = Field(description="같은 기간 지수 등락률 (%)")


class PerformanceOut(BaseModel):
    items: list[NoteReturnOut] = Field(description="회고를 낼 수 있었던 메모만 담긴다")
    error: str | None = Field(description="시세를 못 받았으면 그 이유")


@router.get("/performance", summary="메모 회고 — 쓴 뒤 얼마나 올랐나")
async def note_performance(
    symbol: str | None = Query(None, description="종목 코드. 없으면 전체"),
    limit: int = Query(50, ge=1, le=service.MAX_LIMIT),
) -> PerformanceOut:
    """메모를 쓴 뒤 주가가 어떻게 됐는지를 메모별로 돌려준다.

    **목록과 따로 두었다.** `GET /api/notes` 는 DB 만 읽어 즉시 답하는 경로다. 여기에
    회고를 합치면 토스가 답할 때까지 메모 본문이 안 뜨고, 토스가 막힌 날에는 메모가
    통째로 빈다. 화면은 목록을 먼저 그리고 회고를 나중에 채운다.

    회고를 낼 수 없는 메모(상장 전, 거래 정지, 종가를 못 받은 종목)는 그냥 빠진다.
    """
    items, error = await note_return.note_returns(service.list_notes(symbol, limit=limit))
    return PerformanceOut(items=[NoteReturnOut(**vars(i)) for i in items], error=error)


@router.post("", summary="메모 쓰기", status_code=201)
def create_note(payload: NoteIn) -> NoteResponse:
    try:
        return _out(service.create(payload.symbol, payload.body, payload.tags))
    except service.NoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{note_id}", summary="메모 고치기")
def update_note(payload: NoteBody, note_id: int = Path(ge=1)) -> NoteResponse:
    """작성 시각은 그대로 두고 고친 시각만 새로 찍는다.

    언제 그 판단을 했는지가 메모의 값어치라, 고쳤다고 작성 시각을 덮으면 안 된다.
    """
    try:
        return _out(service.update(note_id, payload.body, payload.tags))
    except service.NoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{note_id}", summary="메모 지우기")
def delete_note(note_id: int = Path(ge=1)) -> dict[str, bool]:
    """없던 메모여도 404 로 만들지 않는다 — 결과가 같기 때문이다."""
    return {"removed": service.remove(note_id)}
