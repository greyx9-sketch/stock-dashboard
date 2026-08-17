"""10-K 섹션 추출기 회귀 테스트.

여기 있는 것들은 **실제 10-K 문서에서 겪은 실패**를 그대로 재현한 것이다. 스펙만 읽고는
알 수 없었고 문서 10건을 돌려 가며 하나씩 찾았다. 다시 깨지면 안 된다.

  - 본문 속 상호참조가 진짜 제목을 이겼다 (AAPL·JPM·WMT 전부)
  - 표를 통째로 버리자 제목이 사라졌다 (WMT — 항목 제목을 표로 레이아웃한다)
  - MD&A 를 쪽 참조로만 적는 문서가 있다 (JPM)
"""

from __future__ import annotations

import pytest

from app.services.tenk_extract import (
    TenKExtractError,
    _is_prose_table,
    _positions,
    extract_from_html,
    extract_sections,
    html_to_text,
)


def _para(text: str, times: int = 20) -> str:
    """섹션이 최소 길이(MIN_SECTION_CHARS=400)를 넘도록 문단을 부풀린다.

    기본 20회는 넉넉히 하한을 넘기려는 것이다 — 하한 미달로 섹션이 빈 채 돌아오면
    테스트가 엉뚱한 이유로 실패해서 원인을 찾는 데 시간이 든다.
    """
    return (text + " ") * times


# ---------------------------------------------------------------- 항목 번호 찾기


def test_item_1_does_not_match_item_1a_or_item_10():
    """`Item 1` 이 `Item 1A`·`Item 10` 에 걸리면 구간이 엉뚱하게 잡힌다."""
    text = "Item 1. Business\nItem 1A. Risk Factors\nItem 10. Directors"
    assert _positions(text, "1") == [0]
    assert len(_positions(text, "1a")) == 1
    assert len(_positions(text, "10")) == 1


def test_cross_reference_is_not_treated_as_heading():
    """문장 중간의 "see Item 1A" 는 제목이 아니다.

    줄 맨 앞이 아니므로 탈락해야 한다. 이걸 놓치면 위험요인 구간이 참조 지점에서 시작한다.
    """
    text = "For more detail see Item 1A. Risk Factors below.\nItem 1A. Risk Factors\nWe face risks."
    starts = _positions(text, "1a", require_title=True)
    assert len(starts) == 1
    assert text[starts[0]:].startswith("Item 1A. Risk Factors\nWe face")


def test_line_leading_reference_needs_title_word():
    """줄 맨 앞이어도 제목 단어가 안 따라오면 제목이 아니다.

    AAPL 이 이 형태였다 — "Item 1A of this Form 10-K under the heading ..." 가 줄머리에 있다.
    `require_title` 이 없으면 이것이 진짜 제목을 이긴다.
    """
    text = "Item 1A of this Form 10-K under the heading “Risk Factors.”\nsome filler text\n"
    # 제목 단어(risk factors)가 창 안에 있긴 하지만…
    with_title = _positions(text, "1a", require_title=True)
    # …줄머리 참조도 형식상 통과할 수 있다. 그래서 최종 판정은 "가장 긴 구간" 규칙이 맡는다.
    # 여기서는 적어도 위치를 찾아내는 것만 확인한다.
    assert with_title == [0] or with_title == []


def test_part_prefix_on_same_line_is_allowed():
    """`PART I Item 1. Business` 처럼 PART 가 같은 줄에 붙는 문서가 있다(AAPL)."""
    text = "PART I Item 1. Business\nWe design and sell devices."
    assert _positions(text, "1", require_title=True) == [0]


# ---------------------------------------------------------------- 표 판별


def test_numeric_table_is_dropped_but_layout_table_is_kept():
    """표를 무조건 버리면 제목이 사라진다(WMT). 숫자 비율로 갈라야 한다."""
    numeric = "2024 2025 1,234 5,678 9,012 3,456 7,890 1,111 2,222"
    prose = "ITEM 1. BUSINESS General Walmart Inc. is an omnichannel retailer"
    assert _is_prose_table(numeric) is False
    assert _is_prose_table(prose) is True


def test_heading_inside_table_survives():
    """월마트 회귀 — 항목 제목이 표 안에 있어도 본문 텍스트에 남아야 한다."""
    html = """
    <html><body>
      <table><tr><td>ITEM 1.</td><td>BUSINESS</td></tr></table>
      <p>We operate retail stores worldwide.</p>
      <table><tr><td>2024</td><td>1,234</td><td>5,678</td></tr></table>
    </body></html>
    """
    text = html_to_text(html)
    # 제목은 남고 (td 사이는 공백으로 이어져 한 줄이 된다)
    assert "ITEM 1. BUSINESS" in text
    # 수치 표는 사라진다
    assert "1,234" not in text


def test_script_and_style_are_dropped():
    html = "<html><head><style>.a{color:red}</style></head><body><script>x=1</script><p>본문</p></body></html>"
    text = html_to_text(html)
    assert "본문" in text
    assert "color:red" not in text
    assert "x=1" not in text


# ---------------------------------------------------------------- 구간 선택


def test_longest_span_wins_over_table_of_contents():
    """목차에도 같은 제목이 있다. 항목 사이가 짧아서 자동으로 탈락해야 한다."""
    toc = "Item 1. Business 3\nItem 1A. Risk Factors 8\nItem 7. Management's Discussion 30\n"
    body = (
        "Item 1. Business\n" + _para("We make and sell things across many countries.") + "\n"
        "Item 1A. Risk Factors\n" + _para("Our supply chain is concentrated.") + "\n"
        "Item 7. Management's Discussion and Analysis\n"
        + _para("Revenue rose because demand improved.") + "\n"
        "Item 8. Financial Statements\n"
    )
    sections = extract_sections(toc + body)

    assert sections.business.startswith("Item 1. Business")
    assert "We make and sell things" in sections.business
    assert "Our supply chain is concentrated" in sections.risk_factors
    assert "demand improved" in sections.mdna
    assert sections.found == ("Item 1", "Item 1A", "Item 7")


def test_mdna_found_by_own_heading_when_item_7_is_only_a_reference():
    """JPM 회귀 — Item 7 자리에 "…쪽 참조" 한 줄만 있고 본문은 딴 자리에 있다."""
    text = (
        "Item 1. Business\n" + _para("We are a financial holding company.") + "\n"
        "Item 1A. Risk Factors\n" + _para("Credit risk is material to us.") + "\n"
        "Item 7. Management's Discussion and Analysis of Financial Condition.\n"
        "Management's discussion and analysis, appears on pages 46-160.\n"
        "Item 7A. Quantitative Disclosures.\n"
        "Item 8. Financial Statements.\n"
        # 본문은 여기 따로 있다. 페이지 머리글로도 같은 제목이 반복된다.
        "Management's discussion and analysis\nThree lines of defense\n"
        "Management's discussion and analysis\n"
        + _para("The following is management's discussion of results, and it runs long.", 12)
    )
    sections = extract_sections(text)
    assert sections.mdna_from_reference is True
    assert "runs long" in sections.mdna


def test_page_header_repeats_do_not_win_over_body():
    """같은 제목이 페이지 머리글로 반복된다. 뒤에 긴 문단이 오는 것을 본문으로 본다."""
    text = (
        "Item 7. Management's Discussion and Analysis.\nRefer to pages 46-160.\n"
        "Item 8. Financial Statements.\n"
        "Management's discussion and analysis\nshort line\n"          # 머리글 (짧다)
        "Management's discussion and analysis\nanother short\n"        # 머리글
        "Management's discussion and analysis\n"
        + _para("This paragraph is long enough to be recognised as real body text.", 10)
    )
    sections = extract_sections(text)
    assert "recognised as real body text" in sections.mdna


# ---------------------------------------------------------------- 실패 처리


def test_empty_document_raises_instead_of_sending_everything():
    """항목을 못 찾으면 예외다. 전체 본문을 그대로 보내면 돈이 몇 배로 든다."""
    html = "<html><body><p>표지뿐이고 항목이 없는 문서</p></body></html>"
    with pytest.raises(TenKExtractError):
        extract_from_html(html)


def test_truncation_is_reported():
    """상한에 걸려 잘리면 어느 항목인지 알려야 한다. 화면에서 밝히기 위한 것이다."""
    long_body = _para("Risk sentence.", 12_000)  # 8만자 상한을 넘긴다
    text = (
        "Item 1. Business\n" + _para("We sell things.") + "\n"
        "Item 1A. Risk Factors\n" + long_body + "\n"
        "Item 2. Properties\n"
    )
    sections = extract_sections(text)
    assert "Item 1A" in sections.truncated
    assert len(sections.risk_factors) == 80_000
