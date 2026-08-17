"""사업보고서 원문에서 분석에 쓸 절을 잘라낸다.

미국 10-K 를 다루는 `tenk_extract.py` 의 국내판이다. 하는 일은 같지만 문서가 전혀 달라
코드를 공유하지 않는다.

**10-K 와 다른 점 셋** — 실제 원문을 열어 보고 확인한 것들이다.

1. **HTML 이 아니라 DART 자체 XML 이다**(`dart4.xsd`). 태그가 대문자이고
   `<SECTION-1>`·`<TITLE>` 로 목차가 실제 계층 구조로 들어 있다. 10-K 처럼 본문에서
   제목을 정규식으로 더듬을 필요가 없다 — **훨씬 안정적이다.**

2. **목차가 법정 서식이라 회사마다 같다.** "II. 사업의 내용", "IV. 이사의 경영진단 및
   분석의견" 이 항상 그 이름으로 있다. 월마트가 제목을 표로 배치하는 식의 변주가 없다.

3. **위험요인에 해당하는 항목이 없다.** 10-K 의 Item 1A 처럼 위험만 모아 둔 절이 국내
   서식에는 없다. 대신 여기저기 흩어져 있다:
     - II-5. 위험관리 및 파생거래
     - XI. 그 밖에 투자자 보호를 위하여 필요한 사항 (소송·제재·우발부채)
   그래서 XI 를 따로 뽑아 함께 보낸다. 흩어진 것을 모아 주는 것이 이 기능의 값어치다.

ZIP 안에는 본문 말고 첨부(감사보고서 등)도 들어 있다. 본문은 `{접수번호}.xml` 이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

# 안쪽을 통째로 버리는 태그.
_DROP_TAGS = frozenset({"summary", "extraction", "image", "img", "img-caption"})

# 줄바꿈으로 바꿀 태그. DART XML 은 대문자지만 html.parser 가 소문자로 넘겨준다.
_BLOCK_TAGS = frozenset(
    {"p", "title", "tr", "pgbrk", "section-1", "section-2", "section-3", "library", "table-group"}
)

# 표를 버릴지 남길지 — 숫자 비율. 재무 수치 표는 XBRL 로 이미 갖고 있어 버리고(절대 규칙 3),
# 서술이 든 표는 남긴다. 10-K 에서 쓴 것과 같은 기준이다.
TABLE_DIGIT_RATIO = 0.20

MAX_XML_BYTES = 40_000_000

# 절별 글자 상한. 이 상한이 곧 비용 상한이다(대략 한글 2~3자 = 1토큰).
LIMIT_BUSINESS = 40_000
LIMIT_MDNA = 30_000
LIMIT_INVESTOR = 30_000

MIN_SECTION_CHARS = 300


class DartExtractError(Exception):
    """원문을 읽거나 절을 찾는 데 실패."""


@dataclass(frozen=True)
class ReportSections:
    """잘라낸 절들. 못 찾은 것은 빈 문자열이다."""

    business: str  # II. 사업의 내용
    mdna: str  # IV. 이사의 경영진단 및 분석의견
    investor: str  # XI. 그 밖에 투자자 보호를 위하여 필요한 사항

    truncated: tuple[str, ...] = ()

    @property
    def found(self) -> tuple[str, ...]:
        names = []
        if self.business:
            names.append("사업의 내용")
        if self.mdna:
            names.append("경영진단")
        if self.investor:
            names.append("투자자 보호사항")
        return tuple(names)

    @property
    def total_chars(self) -> int:
        return len(self.business) + len(self.mdna) + len(self.investor)

    @property
    def is_empty(self) -> bool:
        return self.total_chars == 0


def _digit_ratio(text: str) -> float:
    compact = len(text) - text.count(" ") - text.count("\n")
    if compact == 0:
        return 1.0
    return sum(map(text.count, "0123456789")) / compact


def _is_prose_table(text: str) -> bool:
    if len(text) == text.count(" ") + text.count("\n"):
        return False
    return _digit_ratio(text) <= TABLE_DIGIT_RATIO


class _TextExtractor(HTMLParser):
    """DART XML 에서 텍스트만 뽑는다.

    XML 이지만 태그 구조가 HTML 과 닮아 있어 표준 html.parser 로 충분하다.
    XML 파서를 쓰면 깨진 문서 하나에 통째로 실패하는데, 이쪽은 관대하게 넘어간다.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._drop_tag: str | None = None
        self._drop_depth = 0
        self._table_depth = 0
        self._table_parts: list[str] = []

    def _out(self) -> list[str]:
        return self._table_parts if self._table_depth else self._parts

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self._drop_tag is not None:
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
        if tag in ("td", "th", "te", "tu"):
            # 칸 사이는 공백. 줄바꿈으로 끊으면 한 문장이 조각난다.
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
        if self._table_parts:
            buffered = "".join(self._table_parts)
            self._table_parts = []
            if _is_prose_table(buffered):
                self._parts.append(buffered)
        return "".join(self._parts)


def xml_to_text(xml: str) -> str:
    """DART XML 조각 → 평문. CPU 를 쓰므로 서버에서는 asyncio.to_thread 로 감싼다."""
    if len(xml) > MAX_XML_BYTES:
        raise DartExtractError(
            f"본문이 너무 큽니다({len(xml) / 1_000_000:.1f}MB). 분석하지 않습니다."
        )
    parser = _TextExtractor()
    parser.feed(xml)
    parser.close()
    text = parser.text()

    text = text.replace("\xa0", " ").replace("　", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n[ \n]*", "\n", text)
    return text.strip()


# ------------------------------------------------------------------ 절 나누기

_SECTION_OPEN = re.compile(r"<SECTION-1\b[^>]*>", re.IGNORECASE)
_TITLE = re.compile(r"<TITLE\b[^>]*>(.*?)</TITLE>", re.IGNORECASE | re.DOTALL)


def _plain(fragment: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", fragment).split())


def split_sections(xml: str) -> list[tuple[str, str]]:
    """본문 XML 을 (대분류 제목, XML 조각) 목록으로 나눈다.

    `<SECTION-1>` 이 대분류(I·II·III…) 하나에 대응한다. 여는 태그 위치로 자른다 —
    닫는 태그를 짝지어 세는 것보다 단순하고, 중간에 태그가 깨져도 버틴다.
    """
    opens = [m.start() for m in _SECTION_OPEN.finditer(xml)]
    if not opens:
        return []

    bounds = opens + [len(xml)]
    sections: list[tuple[str, str]] = []
    for i, start in enumerate(opens):
        chunk = xml[start : bounds[i + 1]]
        title_match = _TITLE.search(chunk)
        title = _plain(title_match.group(1)) if title_match else ""
        sections.append((title, chunk))
    return sections


# 대분류를 알아보는 열쇳말. 로마숫자는 회사마다 붙였다 안 붙였다 해서 쓰지 않는다.
_WANTED = {
    "business": ("사업의 내용",),
    "mdna": ("경영진단",),
    "investor": ("투자자 보호",),
}


def _pick(sections: list[tuple[str, str]], keys: tuple[str, ...]) -> str:
    """열쇳말이 제목에 든 절 중 가장 긴 것. 같은 말이 상세표에도 나오는 경우를 피한다."""
    hits = [chunk for title, chunk in sections if any(k in title for k in keys)]
    return max(hits, key=len) if hits else ""


def _cut(text: str, limit: int) -> tuple[str, bool]:
    if len(text) > limit:
        return text[:limit].rstrip(), True
    return text, False


def extract_sections(xml: str) -> ReportSections:
    """본문 XML → 분석에 보낼 세 절."""
    sections = split_sections(xml)
    if not sections:
        raise DartExtractError(
            "본문에서 목차 구조(SECTION-1)를 찾지 못했습니다.\n"
            "  사업보고서가 아닌 다른 서식이거나 형식이 특이한 문서일 수 있습니다."
        )

    bodies: dict[str, str] = {}
    for name, keys in _WANTED.items():
        chunk = _pick(sections, keys)
        body = xml_to_text(chunk) if chunk else ""
        bodies[name] = body if len(body) >= MIN_SECTION_CHARS else ""

    business, cut_b = _cut(bodies["business"], LIMIT_BUSINESS)
    mdna, cut_m = _cut(bodies["mdna"], LIMIT_MDNA)
    investor, cut_i = _cut(bodies["investor"], LIMIT_INVESTOR)

    truncated = tuple(
        label
        for label, cut in (
            ("사업의 내용", cut_b),
            ("경영진단", cut_m),
            ("투자자 보호사항", cut_i),
        )
        if cut
    )
    return ReportSections(
        business=business, mdna=mdna, investor=investor, truncated=truncated
    )


def is_annual_report(report_name: str) -> bool:
    """공시 이름이 사업보고서인지.

    `startswith` 로 보면 안 된다. 정정된 보고서는 이름 앞에 말머리가 붙는다 —
    `[기재정정]사업보고서 (2025.12)`, `[첨부정정]사업보고서` 처럼. KB금융이 그랬다.
    정정본이 오히려 최신이고 정확한 판이므로 받아들이는 것이 맞다.

    `in` 으로 봐도 반기보고서·분기보고서가 잘못 걸리지 않는다 — 그 이름들에는
    "사업보고서" 라는 문자열이 들어 있지 않다.
    """
    return "사업보고서" in report_name


def main_document(documents: dict[str, str], receipt_no: str) -> str:
    """ZIP 안 여러 파일 중 본문을 고른다.

    본문은 `{접수번호}.xml` 이고 나머지는 첨부(감사보고서 등)다. 이름이 다른 문서를
    만나도 멈추지 않도록 가장 큰 파일로 물러선다.
    """
    exact = documents.get(f"{receipt_no}.xml")
    if exact:
        return exact
    if not documents:
        raise DartExtractError("공시 원문이 비어 있습니다.")
    return max(documents.values(), key=len)


def extract_from_documents(documents: dict[str, str], receipt_no: str) -> ReportSections:
    sections = extract_sections(main_document(documents, receipt_no))
    if sections.is_empty:
        raise DartExtractError(
            "본문에서 「사업의 내용」·「경영진단」 절을 찾지 못했습니다.\n"
            "  원문 링크로 직접 확인해 주세요."
        )
    return sections
