"""종목 메모 테스트.

메모는 **지워지면 복구할 수 없는 유일한 데이터**다. 시세·재무·공시는 언제든 다시 받아
올 수 있지만 사용자가 쓴 글은 그렇지 않다. 그래서 여기서는 "저장이 되는가"보다
**잃지 않는가 / 시각이 정확한가**를 본다.

시각이 특히 위험하다. SQLite 는 시간대를 저장하지 않아 읽어 올 때 naive 로 돌아오는데,
그대로 내보내면 화면이 브라우저 지역 시각으로 읽어 9시간 어긋난다. 언제 그 판단을
했는지가 메모의 값어치이므로 이건 사소한 오차가 아니다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.base import init_db
from app.services import notes as service


@pytest.fixture(autouse=True)
def clean_notes():
    """테스트끼리 메모가 새지 않게 매번 비운다. conftest 가 임시 DB 를 쓰게 해 둔다."""
    init_db()
    for note in service.list_notes(limit=service.MAX_LIMIT):
        service.remove(note.id)
    yield


# ---------------------------------------------------------------- 기본 왕복


def test_write_and_read_back():
    created = service.create("005930", "반도체 사이클 저점 통과 여부 확인 필요")
    found = service.list_notes("005930")
    assert [n.id for n in found] == [created.id]
    assert found[0].body == "반도체 사이클 저점 통과 여부 확인 필요"


def test_notes_are_newest_first():
    """일지는 최신 것이 위에 있어야 읽힌다."""
    service.create("005930", "첫 번째")
    service.create("005930", "두 번째")
    bodies = [n.body for n in service.list_notes("005930")]
    assert bodies == ["두 번째", "첫 번째"]


def test_notes_are_scoped_to_the_symbol():
    """다른 종목의 메모가 섞이면 기록으로서 쓸모가 없어진다."""
    service.create("005930", "삼성 메모")
    service.create("AAPL", "애플 메모")
    assert [n.body for n in service.list_notes("005930")] == ["삼성 메모"]
    assert [n.body for n in service.list_notes("AAPL")] == ["애플 메모"]


def test_symbol_case_is_normalized():
    """`aapl` 로 쓴 메모가 `AAPL` 화면에서 안 보이면 사라진 것처럼 느껴진다."""
    service.create("aapl", "소문자로 썼다")
    assert len(service.list_notes("AAPL")) == 1
    assert service.list_notes("AAPL")[0].symbol == "AAPL"


def test_market_is_recorded():
    assert service.create("005930", "x").market == "KR"
    assert service.create("AAPL", "x").market == "US"


# ---------------------------------------------------------------- 시각


def test_timestamps_carry_a_timezone():
    """오프셋 없이 내보내면 화면이 지역 시각으로 읽어 9시간 어긋난다."""
    note = service.create("005930", "시각 확인")
    parsed = datetime.fromisoformat(note.created_at)
    assert parsed.tzinfo is not None


def test_fresh_note_is_not_marked_edited():
    """작성·수정 시각의 기본값이 각각 계산되면 마이크로초가 어긋나 전부 "수정됨" 이 된다."""
    assert service.create("005930", "방금 썼다").edited is False
    assert service.list_notes("005930")[0].edited is False


def test_editing_keeps_the_original_time_and_flags_it():
    """언제 그 판단을 했는지가 메모의 값어치다. 고쳤다고 작성 시각을 덮으면 안 된다."""
    created = service.create("005930", "처음 생각")
    updated = service.update(created.id, "고친 생각")
    assert updated.created_at == created.created_at
    assert updated.body == "고친 생각"
    assert updated.edited is True


# ---------------------------------------------------------------- 태그


def test_tags_round_trip():
    note = service.create("005930", "x", ["반도체", "장기"])
    assert service.list_notes("005930")[0].tags == ["반도체", "장기"]
    assert note.tags == ["반도체", "장기"]


def test_tag_hash_and_spaces_are_stripped():
    """`#반도체` 라고 써도 `반도체` 와 같은 태그여야 한다."""
    service.create("005930", "x", ["  #반도체 ", "장기"])
    assert service.list_notes("005930")[0].tags == ["반도체", "장기"]


def test_duplicate_tags_are_collapsed():
    service.create("005930", "x", ["반도체", "반도체", "#반도체"])
    assert service.list_notes("005930")[0].tags == ["반도체"]


def test_empty_tags_are_dropped():
    service.create("005930", "x", ["", "  ", "#"])
    assert service.list_notes("005930")[0].tags == []


# ---------------------------------------------------------------- 거절


def test_empty_body_is_rejected():
    """빈 메모가 쌓이면 목록이 지저분해지고 지우는 것도 일이다."""
    with pytest.raises(service.NoteError):
        service.create("005930", "   ")


def test_too_long_body_is_rejected():
    with pytest.raises(service.NoteError):
        service.create("005930", "가" * (service.MAX_BODY + 1))


def test_editing_a_deleted_note_says_so():
    note = service.create("005930", "곧 지울 것")
    service.remove(note.id)
    with pytest.raises(service.NoteError):
        service.update(note.id, "되살리기")


def test_removing_twice_is_not_an_error():
    """결과가 같으므로 오류로 다루지 않는다."""
    note = service.create("005930", "x")
    assert service.remove(note.id) is True
    assert service.remove(note.id) is False


def test_body_is_stripped_but_line_breaks_survive():
    """메모는 문단으로 쓰는 글이다. 줄바꿈을 없애면 원래 글이 아니게 된다."""
    note = service.create("005930", "  첫 줄\n\n둘째 줄  ")
    assert note.body == "첫 줄\n\n둘째 줄"
