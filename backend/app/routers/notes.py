"""종목 메모 엔드포인트.

기획서가 **"이 프로젝트의 차별점"** 이라 부른 기능이다. 증권사 HTS 에는 없다.

관심종목과 마찬가지로 화면이 서버 상태를 바꾸는 경로다. 읽기 전용 대시보드라는 원칙과
어긋나 보이지만, 메모는 사용자 자신이 쓴 글이고 매매·계좌와는 무관하다.

브라우저 저장소를 쓰지 않으므로(절대 규칙 6) 메모는 서버 DB 에 있다. 그래서 매일 백업에
함께 들어가고, 브라우저를 지워도 사라지지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.services import notes as service

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
