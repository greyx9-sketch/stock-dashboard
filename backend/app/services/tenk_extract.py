"""10-K 본문에서 Item 1(사업)·1A(위험요인)·7(MD&A)을 잘라낸다.

LLM 에 보내기 **전** 단계다. 여기서 얼마나 정확히 자르느냐가 분석 품질과 비용을
동시에 결정한다 — 잘못 자르면 목차 몇 줄만 보내거나(품질), 문서 전체를 보낸다(비용).

새 라이브러리를 쓰지 않고 표준 라이브러리 `html.parser` 로만 만든다. 서버 메모리가
1GB 이고, 수치 표는 이미 XBRL 로 갖고 있어서 걷어내도 되기 때문에 태그 제거 수준으로 충분하다.

실제 10-K 를 열어 보고 확인한 이 문서들의 성질:

- **앞머리 목차(Table of Contents)에 항목 제목이 그대로 한 번 더 나온다.** 첫 매치를
  쓰면 목차 한 줄만 잘린다. 그래서 모든 매치를 모아 **가장 긴 구간**을 고른다 —
  목차는 항목 사이가 수십 글자라 자동으로 탈락한다.
- 표기가 회사마다 다르다: `Item 1A.` / `ITEM 1A —` / `Item 1A:` / 사이에 전각공백.
- 본문 안에서도 다른 항목을 상호참조한다("see Item 1A. Risk Factors"). 이것도
  가장 긴 구간 규칙으로 대부분 걸러진다.
- iXBRL 문서는 `<ix:header>` 안에 사람이 읽지 않는 태깅 데이터가 잔뜩 들어 있다. 버린다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

# 안쪽 내용을 통째로 버리는 태그.
_DROP_TAGS = frozenset({"script", "style", "ix:header"})

# 줄바꿈으로 바꿀 블록 태그. 없으면 제목과 본문이 한 덩어리로 붙는다.
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section"}
)

# 표를 버릴지 남길지 가르는 기준 — 공백을 뺀 글자 중 숫자 비율.
#
# 처음에는 `<table>` 을 전부 버렸다. 수치는 XBRL 에서 직접 계산하니까(절대 규칙 3)
# 필요 없고 토큰만 먹는다고 봤기 때문이다. 그런데 **월마트는 항목 제목 자체를 표 안에
# 넣어 레이아웃을 잡는다.** 표를 버리자 "Item 1. Business" 제목이 통째로 사라져
# 세 항목을 하나도 못 찾았다.
#
# 그래서 표를 내용으로 판별한다. 재무 수치 표는 숫자 비율이 높고, 레이아웃용 표와
# 서술이 든 표는 낮다.
TABLE_DIGIT_RATIO = 0.20

# 방어선. 정상적인 10-K 는 아무리 커도 20MB 안쪽이다.
MAX_HTML_BYTES = 40_000_000

# 섹션별 글자 상한. 이 상한이 곧 비용 상한이다(대략 4글자 = 1토큰).
LIMIT_BUSINESS = 40_000
LIMIT_RISK = 80_000
LIMIT_MDNA = 60_000

# 이보다 짧으면 목차나 상호참조를 잘못 잡은 것으로 본다.
MIN_SECTION_CHARS = 400


class TenKExtractError(Exception):
    """본문을 읽거나 항목을 찾는 데 실패."""


@dataclass(frozen=True)
class TenKSections:
    """잘라낸 세 섹션. 못 찾은 것은 빈 문자열이다."""

    business: str  # Item 1
    risk_factors: str  # Item 1A
    mdna: str  # Item 7

    # 상한에 걸려 잘렸는지. 화면에 "일부만 분석함"을 표시하는 데 쓴다.
    truncated: tuple[str, ...] = ()

    # MD&A 를 Item 7 자리가 아니라 자체 제목으로 찾았는지(참조 형식 문서).
    mdna_from_reference: bool = False

    @property
    def found(self) -> tuple[str, ...]:
        names = []
        if self.business:
            names.append("Item 1")
        if self.risk_factors:
            names.append("Item 1A")
        if self.mdna:
            names.append("Item 7")
        return tuple(names)

    @property
    def total_chars(self) -> int:
        return len(self.business) + len(self.risk_factors) + len(self.mdna)

    @property
    def is_empty(self) -> bool:
        return self.total_chars == 0


def _digit_ratio(text: str) -> float:
    """공백을 뺀 글자 중 숫자 비율. 표 판별과 목차 판별에 함께 쓴다."""
    compact = len(text) - text.count(" ") - text.count("\n")
    if compact == 0:
        return 1.0
    return sum(map(text.count, "0123456789")) / compact


def _is_prose_table(text: str) -> bool:
    """숫자가 적으면 서술·레이아웃용 표로 보고 남긴다."""
    if len(text) == text.count(" ") + text.count("\n"):
        return False
    return _digit_ratio(text) <= TABLE_DIGIT_RATIO


class _TextExtractor(HTMLParser):
    """태그를 걷어내고 텍스트만 모은다."""

    def __init__(self) -> None:
        # convert_charrefs=True 가 기본이라 &nbsp; 같은 엔티티는 알아서 문자로 바뀐다.
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._drop_tag: str | None = None
        self._drop_depth = 0
        # 표는 일단 따로 담아 두고, 닫힐 때 숫자 비율을 보고 남길지 정한다.
        self._table_depth = 0
        self._table_parts: list[str] = []

    def _out(self) -> list[str]:
        return self._table_parts if self._table_depth else self._parts

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self._drop_tag is not None:
            # 버리는 중. 같은 태그가 중첩되면 깊이를 센다.
            if tag == self._drop_tag:
                self._drop_depth += 1
            return
        if tag in _DROP_TAGS:
            self._drop_tag = tag
            self._drop_depth = 1
            return
        if tag == "table":
            self._table_depth += 1
            self._out().append("\n")
            return
        if tag in ("td", "th"):
            # 칸 사이는 공백으로 잇는다. 줄바꿈으로 끊으면 "Item 1." 과 "Business" 가
            # 다른 줄로 갈라져 제목을 못 알아본다.
            self._out().append(" ")
            return
        if tag in _BLOCK_TAGS:
            self._out().append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._drop_tag is not None:
            if tag == self._drop_tag:
                self._drop_depth -= 1
                if self._drop_depth <= 0:
                    self._drop_tag = None
            return
        if tag == "table":
            if self._table_depth > 0:
                self._table_depth -= 1
            if self._table_depth == 0 and self._table_parts:
                buffered = "".join(self._table_parts)
                self._table_parts = []
                if _is_prose_table(buffered):
                    self._parts.append(buffered)
                self._parts.append("\n")
            return
        if tag in _BLOCK_TAGS:
            self._out().append("\n")

    def handle_data(self, data: str) -> None:
        if self._drop_tag is None:
            self._out().append(data)

    def text(self) -> str:
        # 닫히지 않은 표가 남아 있으면(깨진 HTML) 같은 규칙으로 판정해 흘려보낸다.
        if self._table_parts:
            buffered = "".join(self._table_parts)
            self._table_parts = []
            if _is_prose_table(buffered):
                self._parts.append(buffered)
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    """공시 HTML → 평문. CPU 를 쓰므로 서버에서는 asyncio.to_thread 로 감싼다."""
    if len(html) > MAX_HTML_BYTES:
        raise TenKExtractError(
            f"본문이 너무 큽니다({len(html) / 1_000_000:.1f}MB). "
            "정상적인 10-K 가 아닐 수 있어 분석하지 않습니다."
        )

    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = parser.text()

    # 줄바꿈 없는 공백(\xa0 등)을 보통 공백으로. 정규식 매칭이 이것 때문에 자주 빗나간다.
    text = text.replace("\xa0", " ").replace(" ", " ").replace(" ", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n[ \n]*", "\n", text)
    return text.strip()


# 항목 번호 뒤에 와야 하는 제목. 상호참조("…자세한 내용은 Item 1A 참조")를 걸러내는
# 두 번째 장치다. 첫 번째는 "줄 맨 앞이어야 한다"는 조건이고, 이것만으로는 부족했다.
_TITLES = {
    "1": r"business",
    "1a": r"risk\s*factors?",
    "7": r"management|discussion\s+and\s+analysis",
}

# 제목이 번호 바로 뒤에 붙기도 하고 다음 줄로 넘어가기도 해서 여유를 둔다.
_TITLE_WINDOW = 120


def _positions(text: str, item: str, *, require_title: bool = False) -> list[int]:
    """`Item <번호>` 제목이 나오는 모든 위치.

    세 가지 조건을 건다. 실제 10-K 세 건으로 하나씩 확인하며 붙인 것들이다.

    1. `(?![0-9a-z])` — 없으면 "Item 1" 이 "Item 1A" 와 "Item 10" 에도 걸린다.
    2. **줄 맨 앞** — 진짜 제목은 자기 줄에서 시작한다. 문장 중간에 나오는
       "as described in Item 1A" 는 이 조건에서 탈락한다. `PART I` 가 같은 줄
       앞에 붙는 문서가 있어 그것만 예외로 허용한다.
    3. (시작 항목만) **제목 단어가 뒤따라야 한다** — 줄 맨 앞 조건만으로는
       "Item 1A of this Form 10-K under the heading ..." 같은 줄머리 참조가 남는다.
    """
    pattern = re.compile(
        rf"^(?:part\s+[ivx]+[.\s:—–-]*)?item\s*{item}(?![0-9a-z])",
        re.IGNORECASE | re.MULTILINE,
    )
    title = re.compile(_TITLES[item], re.IGNORECASE) if require_title else None

    found: list[int] = []
    for match in pattern.finditer(text):
        if title is not None:
            window = text[match.end() : match.end() + _TITLE_WINDOW]
            if not title.search(window):
                continue
        found.append(match.start())
    return found


def _pick_span(text: str, start_item: str, end_items: list[str]) -> tuple[int, int] | None:
    """(시작, 끝) 중 본문이 가장 긴 조합을 고른다. 목차를 걸러내는 규칙이다.

    목차는 항목 사이가 수십 글자라 자동으로 탈락한다.
    """
    starts = _positions(text, start_item, require_title=True)
    if not starts:
        return None

    ends: list[int] = []
    for item in end_items:
        ends.extend(_positions(text, item))
    ends.sort()

    best: tuple[int, int] | None = None
    for start in starts:
        later = [e for e in ends if e > start]
        # 끝 표시를 못 찾으면 문서 끝까지. Item 8 이 없는 문서는 사실상 없지만,
        # 없다고 섹션을 통째로 버리는 것보다는 낫다.
        end = later[0] if later else len(text)
        if best is None or (end - start) > (best[1] - best[0]):
            best = (start, end)

    if best is None or (best[1] - best[0]) < MIN_SECTION_CHARS:
        return None
    return best


# MD&A 를 "Item 7 … 46–160쪽 참조" 로만 적고 본문은 문서 안 다른 자리에 두는 형식이 있다.
# 은행권에 흔하다(JPM 이 그렇다). 그때 본문을 자체 제목으로 다시 찾기 위한 것들이다.
_MDNA_HEADING = re.compile(
    r"^management[’'`]?s?\s+discussion\s+and\s+analysis",
    re.IGNORECASE | re.MULTILINE,
)
# 같은 제목이 세 가지 모습으로 반복돼서 골라내야 한다(JPM 문서에서 42번 나온다):
#   ① Item 7 자리의 참조 문장 자체 — "…entitled 'MD&A,' appears on pages 46-160"
#   ② MD&A 자체 목차 — "Introduction 46 / Executive Overview 47 / …"
#   ③ 페이지 머리글 — 매 쪽 상단에 같은 제목이 다시 찍힌다
#
# 숫자 비율로 가르려다 실패했다. 본문 시작(0.08)이 페이지 머리글(0.00)보다 오히려 높다 —
# 서두에 쪽 참조가 섞이기 때문이다. 그래서 **뒤에 진짜 문단이 오는가**로 가른다.
# 목차와 머리글은 짧은 줄만 이어지고, 본문 시작에는 긴 문단이 온다.
_MDNA_PROBE = 1_000
_MDNA_PARAGRAPH_CHARS = 180
# ①은 참조 문장 안에서 제목을 한 번 더 부르는 것이라 Item 7 바로 뒤에 붙어 있다. 건너뛴다.
_MDNA_SKIP_AFTER_ITEM7 = 2_000


def _has_paragraph(window: str) -> bool:
    """긴 줄이 하나라도 있으면 서술 문단으로 본다."""
    return any(len(line) >= _MDNA_PARAGRAPH_CHARS for line in window.split("\n"))


def _mdna_by_heading(text: str, after: int) -> tuple[int, int] | None:
    """Item 7 이 참조뿐일 때, MD&A 본문을 자체 제목으로 찾는다.

    조건을 통과하는 **가장 이른** 후보를 쓴다. MD&A 는 서두(개요·실적 설명)가 핵심이라
    뒤쪽 절을 잡으면 정작 필요한 내용을 놓친다.
    """
    for match in _MDNA_HEADING.finditer(text):
        if match.start() < after:
            continue
        if _has_paragraph(text[match.end() : match.end() + _MDNA_PROBE]):
            return match.start(), min(len(text), match.start() + LIMIT_MDNA)
    return None


def _section(text: str, start_item: str, end_items: list[str], limit: int) -> tuple[str, bool]:
    span = _pick_span(text, start_item, end_items)
    if span is None:
        return "", False
    body = text[span[0] : span[1]].strip()
    if len(body) > limit:
        # 앞부분을 남긴다. 위험요인도 MD&A 도 중요한 것이 앞에 온다.
        return body[:limit].rstrip(), True
    return body, False


def extract_sections(text: str) -> TenKSections:
    """평문 10-K 에서 세 섹션을 잘라낸다."""
    business, cut_business = _section(text, "1", ["1a", "1b", "2"], LIMIT_BUSINESS)
    risk, cut_risk = _section(text, "1a", ["1b", "2"], LIMIT_RISK)
    mdna, cut_mdna = _section(text, "7", ["7a", "8"], LIMIT_MDNA)

    # Item 7 자리에 "…쪽 참조" 한 줄만 있는 문서면 본문을 자체 제목으로 다시 찾는다.
    from_reference = False
    if not mdna:
        item7 = _positions(text, "7", require_title=True)
        after = item7[-1] + _MDNA_SKIP_AFTER_ITEM7 if item7 else 0
        span = _mdna_by_heading(text, after=after)
        if span is not None:
            mdna = text[span[0] : span[1]].strip()
            cut_mdna = span[1] - span[0] >= LIMIT_MDNA
            from_reference = True

    truncated = tuple(
        name
        for name, cut in (("Item 1", cut_business), ("Item 1A", cut_risk), ("Item 7", cut_mdna))
        if cut
    )
    return TenKSections(
        business=business,
        risk_factors=risk,
        mdna=mdna,
        truncated=truncated,
        mdna_from_reference=from_reference,
    )


def extract_from_html(html: str) -> TenKSections:
    """HTML 한 덩어리 → 세 섹션. 하나도 못 찾으면 예외."""
    sections = extract_sections(html_to_text(html))
    if sections.is_empty:
        raise TenKExtractError(
            "본문에서 Item 1·1A·7 을 찾지 못했습니다.\n"
            "  표지만 있고 내용은 별도 첨부파일에 있는 형식이거나, 항목 표기가\n"
            "  일반적이지 않은 문서일 수 있습니다. 원문 링크로 직접 확인해 주세요."
        )
    return sections
