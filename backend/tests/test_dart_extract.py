"""사업보고서 절 추출기 회귀 테스트.

DART 원문은 자체 XML(dart4.xsd)이고 `<SECTION-1>`/`<TITLE>` 로 목차가 계층 구조로
들어 있어 10-K 보다 다루기 쉽다. 대신 국내 서식만의 함정이 있고, KB금융에서 실제로 걸렸다:

  - 정정된 보고서는 이름 앞에 말머리가 붙는다 — `[기재정정]사업보고서 (2025.12)`
  - 그 정정본은 원문 파일이 아예 없는 경우가 있다(OpenDART status 014)
"""

from __future__ import annotations

import pytest

from app.services.dart_extract import (
    DartExtractError,
    extract_from_documents,
    extract_sections,
    is_annual_report,
    main_document,
    split_sections,
    xml_to_text,
)


def _para(text: str, times: int = 30) -> str:
    """절이 최소 길이(MIN_SECTION_CHARS=300)를 넘도록 부풀린다.

    한글은 한 글자에 담기는 정보가 많아 문장이 짧다. 영문 기준으로 반복 횟수를 잡으면
    하한에 못 미쳐 절이 빈 채 돌아오고, 테스트가 엉뚱한 이유로 실패한다.
    """
    return (text + " ") * times


def _report(*, mdna: str = "", investor: str = "") -> str:
    """사업보고서 뼈대. 실제 문서의 태그 구조를 따랐다."""
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<DOCUMENT>",
        '<DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>',
        "<SECTION-1><TITLE>I. 회사의 개요</TITLE><P>회사 개요입니다.</P></SECTION-1>",
        "<SECTION-1><TITLE>II. 사업의 내용</TITLE><P>"
        + _para("당사는 반도체와 완제품을 만들어 판매합니다.")
        + "</P></SECTION-1>",
        "<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE><P>재무제표입니다.</P></SECTION-1>",
    ]
    if mdna:
        parts.append(
            "<SECTION-1><TITLE>IV. 이사의 경영진단 및 분석의견</TITLE><P>"
            + mdna
            + "</P></SECTION-1>"
        )
    if investor:
        parts.append(
            "<SECTION-1><TITLE>XI. 그 밖에 투자자 보호를 위하여 필요한 사항</TITLE><P>"
            + investor
            + "</P></SECTION-1>"
        )
    parts.append("</DOCUMENT>")
    return "\n".join(parts)


# ---------------------------------------------------------------- 보고서 이름 판별


@pytest.mark.parametrize(
    "name",
    [
        "사업보고서 (2025.12)",
        "[기재정정]사업보고서 (2025.12)",  # KB금융 회귀 — startswith 로는 놓친다
        "[첨부정정]사업보고서 (2024.12)",
        "[첨부추가]사업보고서",
    ],
)
def test_annual_report_names_accepted(name):
    assert is_annual_report(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "반기보고서 (2026.06)",
        "분기보고서 (2026.03)",
        "[기재정정]반기보고서 (2025.06)",
        "감사보고서",
    ],
)
def test_non_annual_report_names_rejected(name):
    assert is_annual_report(name) is False


# ---------------------------------------------------------------- 본문 파일 고르기


def test_main_document_prefers_exact_receipt_filename():
    """ZIP 안에는 본문 말고 첨부(감사보고서 등)도 있다. 본문은 `{접수번호}.xml` 이다."""
    docs = {
        "20260310002820.xml": "본문",
        "20260310002820_00760.xml": "첨부입니다" * 100,  # 첨부가 더 길 수도 있다
    }
    assert main_document(docs, "20260310002820") == "본문"


def test_main_document_falls_back_to_largest():
    """이름 규칙이 다른 문서를 만나도 멈추지 않는다."""
    docs = {"other_a.xml": "짧다", "other_b.xml": "길다" * 100}
    assert main_document(docs, "20260310002820") == "길다" * 100


def test_main_document_rejects_empty():
    with pytest.raises(DartExtractError):
        main_document({}, "20260310002820")


# ---------------------------------------------------------------- 목차 나누기


def test_split_sections_reads_titles():
    sections = split_sections(_report(mdna=_para("실적이 좋아졌습니다.")))
    titles = [t for t, _ in sections]
    assert "II. 사업의 내용" in titles
    assert "IV. 이사의 경영진단 및 분석의견" in titles


def test_split_sections_empty_when_no_structure():
    assert split_sections("<DOCUMENT><P>구조가 없는 문서</P></DOCUMENT>") == []


# ---------------------------------------------------------------- 텍스트 변환


def test_table_cells_are_joined_with_space_not_newline():
    """칸 사이를 줄바꿈으로 끊으면 「사업의 내용」 같은 제목이 조각난다."""
    xml = "<TABLE><TR><TD>ITEM</TD><TD>1.</TD><TD>사업의 내용</TD></TR></TABLE>"
    text = xml_to_text(xml)
    assert "ITEM 1. 사업의 내용" in text


def test_numeric_table_is_dropped():
    """수치 표는 XBRL 로 이미 갖고 있다. 토큰만 먹으므로 버린다(절대 규칙 3)."""
    xml = (
        "<P>서술 문장입니다.</P>"
        "<TABLE><TR><TD>2024</TD><TD>1,234,567</TD><TD>8,901,234</TD>"
        "<TD>5,678</TD><TD>9,012</TD></TR></TABLE>"
    )
    text = xml_to_text(xml)
    assert "서술 문장입니다" in text
    assert "1,234,567" not in text


def test_summary_block_is_dropped():
    """<SUMMARY> 안은 사람이 읽지 않는 태깅 데이터다."""
    xml = '<SUMMARY><EXTRACTION ACODE="IFRS_YN">Y</EXTRACTION></SUMMARY><P>본문</P>'
    text = xml_to_text(xml)
    assert "본문" in text
    assert "IFRS_YN" not in text


# ---------------------------------------------------------------- 절 뽑기


def test_extracts_three_sections():
    xml = _report(
        mdna=_para("메모리 가격 상승이 실적 개선을 이끌었습니다."),
        investor=_para("계열사에 대한 지급보증이 있습니다."),
    )
    sections = extract_sections(xml)
    assert "반도체와 완제품" in sections.business
    assert "메모리 가격 상승" in sections.mdna
    assert "지급보증" in sections.investor
    assert sections.found == ("사업의 내용", "경영진단", "투자자 보호사항")


def test_missing_optional_sections_are_empty_not_fatal():
    """투자자 보호사항이 없는 회사도 있다. 없다고 실패하지 않는다."""
    sections = extract_sections(_report(mdna=_para("실적을 설명합니다.")))
    assert sections.business
    assert sections.mdna
    assert sections.investor == ""
    assert sections.is_empty is False


def test_no_sections_raises():
    """절을 하나도 못 찾으면 예외다. 전체 본문을 그대로 보내면 돈이 몇 배로 든다."""
    xml = "<DOCUMENT><SECTION-1><TITLE>I. 회사의 개요</TITLE><P>개요만</P></SECTION-1></DOCUMENT>"
    with pytest.raises(DartExtractError):
        extract_from_documents({"20260310002820.xml": xml}, "20260310002820")


def test_no_structure_raises():
    with pytest.raises(DartExtractError):
        extract_sections("<DOCUMENT><P>목차 구조가 없다</P></DOCUMENT>")


def test_longest_match_wins_when_keyword_repeats():
    """같은 열쇳말이 상세표에도 나온다. 본문이 훨씬 길다는 점으로 가른다."""
    xml = (
        "<DOCUMENT>"
        "<SECTION-1><TITLE>XII. 상세표 — 사업의 내용 참고</TITLE><P>짧은 참조</P></SECTION-1>"
        "<SECTION-1><TITLE>II. 사업의 내용</TITLE><P>"
        + _para("실제 본문입니다. 사업을 설명합니다.")
        + "</P></SECTION-1>"
        "</DOCUMENT>"
    )
    sections = extract_sections(xml)
    assert "실제 본문입니다" in sections.business


def test_truncation_is_reported():
    """상한에 걸려 잘리면 어느 절인지 알려야 한다. 화면에서 밝히기 위한 것이다."""
    xml = _report(mdna=_para("실적 설명.", 20_000))  # 3만자 상한을 넘긴다
    sections = extract_sections(xml)
    assert "경영진단" in sections.truncated
    assert len(sections.mdna) == 30_000
