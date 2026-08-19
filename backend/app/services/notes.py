"""종목 메모 — 읽기·쓰기.

외부 API 를 부르지 않는다. DB 하나만 다루므로 전부 동기 함수다(FastAPI 가 동기 경로
함수를 워커 스레드에서 돌리므로 서버가 멈추지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import desc, func, select

from app.models.base import get_session
from app.models.note import Note
from app.services.price_poller import classify_market

# 메모 한 건의 길이 상한. 화면에서 읽을 수 있는 길이를 넘기면 메모가 아니라 문서다.
MAX_BODY = 4000
MAX_TAGS = 200

# 한 번에 돌려줄 개수의 상한.
MAX_LIMIT = 200


class NoteError(Exception):
    """사용자에게 그대로 보여줄 수 있는 실패."""


@dataclass
class NoteOut:
    id: int
    symbol: str
    market: str
    body: str
    tags: list[str]
    created_at: str
    updated_at: str
    edited: bool


def _tags_to_list(raw: str) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _tags_to_text(tags: list[str] | None) -> str:
    """중복을 걷어내고 순서를 지킨다. 같은 태그가 두 번 붙으면 화면이 지저분해진다."""
    seen: list[str] = []
    for tag in tags or []:
        cleaned = tag.strip().lstrip("#")
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    text = ",".join(seen)
    if len(text) > MAX_TAGS:
        raise NoteError(f"태그가 너무 깁니다. 전체 {MAX_TAGS}자 안으로 줄여 주세요.")
    return text


def _aware(value: datetime) -> datetime:
    """SQLite 는 시간대를 저장하지 않아 읽어 올 때 naive 로 돌아온다.

    그대로 내보내면 화면이 그 값을 **브라우저 지역 시각**으로 읽어 9시간 어긋난다.
    저장은 UTC 로 하므로 여기서 UTC 를 붙여 준다.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value).isoformat()


def _out(row: Note) -> NoteOut:
    return NoteOut(
        id=row.id,
        symbol=row.symbol,
        market=row.market,
        body=row.body,
        tags=_tags_to_list(row.tags),
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        # 고친 적이 있는지를 화면에 표시한다. 언제 그 판단을 했는지가 메모의 값어치라,
        # 나중에 고친 것이라면 그 사실이 보여야 한다.
        #
        # 정확히 비교해도 되는 이유: 작성할 때 두 열에 **같은 값**을 박는다(`create` 참고).
        # 열마다 기본값을 따로 계산하게 두면 마이크로초가 어긋나 모든 메모가 "수정됨" 이 된다.
        # 여유를 두는 방법도 있지만, 그러면 쓰자마자 고친 것을 놓친다.
        edited=_aware(row.updated_at) > _aware(row.created_at),
    )


def _clean_body(body: str) -> str:
    text = (body or "").strip()
    if not text:
        raise NoteError("내용을 적어 주세요.")
    if len(text) > MAX_BODY:
        raise NoteError(f"메모가 너무 깁니다. {MAX_BODY}자 안으로 줄여 주세요.")
    return text


def list_notes(symbol: str | None = None, *, limit: int = 50) -> list[NoteOut]:
    """메모 목록. 최신순이다.

    `symbol` 을 주면 그 종목만, 없으면 전체에서 최근 것부터 준다(나중에 "최근 메모"
    피드를 붙일 때 그대로 쓴다).
    """
    limit = min(max(limit, 1), MAX_LIMIT)
    stmt = select(Note).order_by(desc(Note.created_at), desc(Note.id)).limit(limit)
    if symbol:
        stmt = stmt.where(Note.symbol == symbol.strip().upper())
    with get_session() as session:
        return [_out(row) for row in session.execute(stmt).scalars()]


def count_by_symbol(symbol: str) -> int:
    stmt = select(func.count()).select_from(Note).where(Note.symbol == symbol.strip().upper())
    with get_session() as session:
        return session.execute(stmt).scalar_one()


def create(symbol: str, body: str, tags: list[str] | None = None) -> NoteOut:
    symbol = symbol.strip().upper()
    if not symbol:
        raise NoteError("종목 코드가 필요합니다.")

    # 두 시각을 같은 값으로 박는다. 열마다 기본값을 따로 계산하게 두면 마이크로초가
    # 어긋나 방금 쓴 메모가 "수정됨" 으로 보인다.
    now = datetime.now(timezone.utc)
    row = Note(
        symbol=symbol,
        market=classify_market(symbol),
        body=_clean_body(body),
        tags=_tags_to_text(tags),
        created_at=now,
        updated_at=now,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
    return _out(row)


def update(note_id: int, body: str, tags: list[str] | None = None) -> NoteOut:
    text = _clean_body(body)
    tag_text = _tags_to_text(tags)
    with get_session() as session:
        row = session.get(Note, note_id)
        if row is None:
            raise NoteError("이미 지워진 메모입니다.")
        row.body = text
        row.tags = tag_text
        # 작성 시각은 그대로 두고 고친 시각만 새로 찍는다.
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        return _out(row)


def remove(note_id: int) -> bool:
    with get_session() as session:
        row = session.get(Note, note_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
    return True
