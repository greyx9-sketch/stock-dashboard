"""10-K 서술 분석 — SEC 원문을 받아 Claude 에 보내고 결과를 저장한다.

이 프로젝트에서 **유일하게 돈이 나가는 경로**다. 그래서 호출을 둘러싼 방어가 분석
자체보다 코드량이 많다. 개인 프로젝트의 비용 사고는 대개 모델이 비싸서가 아니라
같은 호출이 반복돼서 난다.

겹겹이 둔 상한(콘솔 월 상한은 이 파일 밖, 사용자가 설정):

  1. DB 캐시    같은 (접수번호, 모델, 프롬프트 버전) 이면 절대 다시 부르지 않는다
  2. 하루 상한  .env 의 ANALYSIS_DAILY_LIMIT (기본 20건). **국내 분석과 합쳐 센다** —
                시장별로 따로 세면 설정한 20건이 실제로는 40건이 된다(`llm_budget.py`)
  3. 동시 1건   1 OCPU 서버이기도 하고, 동시 요청이 캐시를 우회해 중복 호출하는 것을 막는다
  4. 입력 상한  부르기 전에 count_tokens(무료)로 재고, 넘으면 잘라서 다시 잰다
  5. 실패 기록  실패도 행으로 남겨 화면을 열 때마다 재시도하는 일을 막는다

**숫자는 LLM 이 만들지 않는다**(CLAUDE.md 절대 규칙 3). 응답 스키마에 수치 필드를 두지
않아 끼워 넣을 자리 자체가 없고, 프롬프트에서도 금지한다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.clients.sec import SecClient, SecError, UsFiling
from app.config import get_settings
from app.models.base import get_session
from app.models.us_analysis import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_PENDING,
    SecAnalysis,
)
from app.models.us_company import SecCompany
from app.services import analysis_batch, llm_budget
from app.services.tenk_extract import (
    TenKExtractError,
    TenKSections,
    TenQSections,
    extract_10q_sections,
    extract_sections,
    html_to_text,
)

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
# 프롬프트·스키마·effort 를 고치면 이 숫자를 올린다. 옛 결과를 지우지 않고 새로 분석된다.
#
# v2: effort 를 medium → high 로 올렸다. medium 에서 MSFT 가 business_summary 만 채우고
#     나머지 네 필드를 빈 채로 돌려줬다(출력 430토큰, 정상은 2,600). 입력은 멀쩡했다 —
#     Item 1A 가 "ITEM 1A. RISK FACTORS" 에서 정확히 시작한 것을 추출기로 확인했다.
#     Sonnet 5 는 낮은 effort 에서 시킨 만큼만 하고 더 파고들지 않는 성향이 있다.
#
# v3: 결과를 **읽히는 카드**로 만들기 위해 세 가지를 바꿨다(2026-09-06).
#     · `one_liner` 추가 — 업계 용어를 금지한 한 문장. 카드의 심장이다.
#     · `segments` 를 문자열에서 {name, what} 으로 — 이름과 설명이 갈려야 카드로 그린다.
#     · `open_questions` 추가 — 이 분석으로 답이 안 나온 것. 빈칸을 밝히는 쪽이 정직하다.
#     스키마가 바뀌었으므로 버전을 올린다. 옛 결과(v2 5건)는 지워지지 않고 남지만
#     화면에는 안 나온다. 다시 분석하면 새 카드로 채워진다.
#
# v4: **경영진 논의를 최신 10-Q 에서 가져온다**(2026-09-06). 10-K 의 Item 7 은 카드를
#     볼 시점에 1년 가까이 묵어 있다. 사업(Item 1)과 위험(Item 1A)은 그대로 연차에서
#     가져온다 — 10-Q 에는 사업 설명이 없고, 10-Q 의 위험은 변경분이라 단독으로 쓰면
#     빠지는 것이 생긴다. 보내는 양은 거의 그대로다(Item 7 을 Item 2 로 바꿔 담을 뿐).
PROMPT_VERSION = 4

MAX_OUTPUT_TOKENS = 16_000
# 섹션 글자 상한(18만 자 ≈ 4.5만 토큰) 때문에 실제로는 거의 걸리지 않는다.
# 토큰화가 유난히 불리한 문서를 위한 마지막 방어선이다.
MAX_INPUT_TOKENS = 180_000
TRIM_ATTEMPTS = 3
# 낮추지 말 것 — PROMPT_VERSION 주석의 medium 실패 사례를 참고. 몇 초 더 걸리는 대신
# 다섯 필드를 제대로 채운다.
EFFORT = "high"

# 가격·동시 실행 잠금·하루 상한은 `llm_budget.py` 에 있다. 국내 분석과 같은 지갑을 쓴다.


class AnalysisError(Exception):
    """분석을 진행할 수 없음. 메시지를 그대로 화면에 보여줄 수 있게 쓴다."""


# ---------------------------------------------------------------- 응답 스키마


class RiskItem(BaseModel):
    """위험요인 한 건."""

    title: str = Field(description="위험을 한 줄로. 예: '중국 생산 의존'")
    why_it_matters: str = Field(
        description="이 위험이 이 회사에 왜 실질적인지 2~3문장. 수치는 쓰지 않는다."
    )
    is_boilerplate: bool = Field(
        description=(
            "모든 상장사 보고서에 형식적으로 붙는 일반 위험이면 true, "
            "이 회사에 특유한 위험이면 false"
        )
    )


class SegmentItem(BaseModel):
    """사업 부문 하나. 이름과 설명을 갈라 둔다 — 카드로 그리려면 둘이 따로여야 한다."""

    name: str = Field(description="부문 이름. 보고서 표기 그대로. 예: 'Experiences'")
    what: str = Field(
        description="이 부문이 무엇을 파는지 한 줄, 15자 안팎. 예: '파크·크루즈·굿즈'"
    )


class TenKAnalysisContent(BaseModel):
    """10-K 서술 분석 결과.

    **수치 필드가 하나도 없다.** 매출·이익·비율은 XBRL 에서 직접 계산해 따로 보여준다.
    """

    one_liner: str = Field(
        description=(
            "이 회사가 무엇으로 돈을 버는지 **한 문장**. 카드 맨 위에 크게 놓인다. "
            "업계 용어 없이, 돈이 어디서 어디로 흐르는지가 드러나게."
        )
    )
    business_summary: str = Field(
        description="이 회사가 무엇을 파는지, 돈이 어디서 나오는지 3~5문장"
    )
    segments: list[SegmentItem] = Field(
        description="사업 부문. 보고서에 부문 구분이 없으면 빈 목록"
    )
    key_risks: list[RiskItem] = Field(
        description="위험요인 중 중요한 순으로 최대 6건. 형식적 문구만 있으면 그렇게 표시"
    )
    mdna_points: list[str] = Field(
        description=(
            "경영진이 실적 변화의 원인으로 든 것. 수치 없이 이유만. "
            "예: '데이터센터 수요 증가가 성장을 이끌었다고 설명'"
        )
    )
    moat_and_competition: str = Field(
        description="경쟁 구도와 회사가 주장하는 우위. 보고서에 근거가 없으면 그렇게 쓴다"
    )
    open_questions: list[str] = Field(
        description=(
            "이 보고서만으로는 답이 안 나온 질문 2~4개. 다음에 무엇을 더 봐야 하는지. "
            "물음표로 끝나는 짧은 문장으로."
        )
    )


SYSTEM_PROMPT = """\
당신은 미국 상장사의 연차보고서(10-K)를 읽고 한국의 금융 실무자에게 설명하는 애널리스트입니다.
읽는 사람은 투자와 공시에 대한 지식이 깊지만 영문 원문을 읽을 시간이 없습니다.

지켜야 할 규칙:

1. **어떤 수치도 쓰지 마십시오.** 금액·성장률·비율·주가·직원 수를 문장에 넣지 않습니다.
   "매출이 늘었다"는 되고 "매출이 12% 늘었다"는 안 됩니다. 수치는 별도의 재무표로
   따로 제공되며, 당신의 역할은 문장 해석뿐입니다. 이것이 가장 중요한 규칙입니다.
2. **원문에 없는 것을 쓰지 마십시오.** 배경지식으로 보충하거나 추론해서 채우지 않습니다.
   보고서에 근거가 없으면 "보고서에 명시되어 있지 않다"고 쓰십시오.
3. **투자 의견을 쓰지 마십시오.** 매수·매도·목표주가·저평가/고평가 판단을 하지 않습니다.
   회사가 무엇을 말했는지를 전달할 뿐입니다.
4. 위험요인은 **형식적 문구와 실질적 위험을 구분**하십시오. 10-K 위험요인의 상당수는
   모든 회사에 똑같이 붙는 정형 문구입니다("자연재해가 발생할 수 있습니다").
   그것을 걸러내 주는 것이 이 분석의 핵심 가치입니다.
5. 한국어로 쓰되 회사명·제품명·부문명 같은 고유명사는 원문 표기를 유지하십시오.
6. 문장은 간결하게. 원문 표현을 그대로 옮기지 말고 뜻을 풀어 쓰십시오.
7. **`one_liner` 는 이 분석의 심장입니다.** 이 회사가 무엇으로 돈을 버는지 한 문장으로
   쓰되, 다음을 지키십시오.
   - **업계 용어를 쓰지 마십시오** — "플랫폼", "생태계", "솔루션", "시너지", "밸류체인",
     "종합 ○○ 기업" 같은 말이 들어가면 실패한 문장입니다. 그 말들은 아무것도 설명하지
     않습니다. 중학생에게 말하듯 쓰십시오.
   - **돈이 어디서 어디로 흐르는지**가 드러나야 합니다. 무엇을 만들어 누구에게 팔고,
     그것이 어떻게 다음 매출로 이어지는지를 화살표로 잇듯 쓰십시오.
   - 좋은 예: "사람들이 평생 좋아하는 캐릭터를 만들어서, 그 하나를 영화 → 구독료 →
     광고 → 장난감 → 놀이공원 입장료까지 수십 년간 계속 우려먹는 회사입니다."
   - 나쁜 예: "종합 엔터테인먼트 플랫폼 기업으로 다각화된 사업 포트폴리오를 보유합니다."
8. `open_questions` 에는 **이 보고서만으로 답이 안 나온 것**을 적으십시오. 답을 아는
   척하지 말고, 다음에 무엇을 더 봐야 하는지를 남기는 자리입니다. 물음표로 끝내십시오.
"""


# ---------------------------------------------------------------- 프롬프트 조립


@dataclass(frozen=True)
class _Document:
    """분석 대상 문서. 연차(10-K) 한 건 + 있으면 최신 분기(10-Q) 한 건.

    **왜 둘을 같이 읽나**: 10-K 는 회계연도가 끝나고 몇 달 뒤에 나오므로, 카드를 볼
    시점에는 경영진 설명이 1년 가까이 묵어 있다. 10-Q 의 MD&A(Item 2)는 몇 주 전
    것이다. 반대로 사업 설명(Item 1)은 10-Q 에 아예 없다 — 그건 연차의 몫이다.
    그래서 **사업·위험은 연차에서, 경영진 설명은 최신 분기에서** 가져온다.

    (국내는 정반대다. 분·반기보고서에는 법령상 경영진단을 싣지 않아서, 국내는
    사업·위험을 최신 분·반기에서 가져오고 경영진단만 사업보고서에서 가져온다.)
    """

    company: SecCompany
    filing: UsFiling
    sections: TenKSections
    quarterly: UsFiling | None = None
    quarterly_sections: TenQSections | None = None

    @property
    def fiscal_year(self) -> int:
        source = self.filing.report_date or self.filing.filing_date
        try:
            return int(source[:4])
        except (ValueError, IndexError):
            return 0


def _build_prompt(doc: _Document, sections: TenKSections) -> str:
    parts = [
        f"회사: {doc.company.name} ({doc.company.ticker})",
        f"보고서: 10-K · {doc.filing.filing_date} 제출 · 회계연도 종료일 "
        f"{doc.filing.report_date or '미상'}",
        "",
    ]
    # 경영진 설명은 최신 분기(10-Q Item 2)가 있으면 그것을 쓴다. 연차의 Item 7 은
    # 같은 이야기를 1년 묵은 채로 하므로 **둘을 같이 보내지 않는다** — 토큰만 늘고
    # 모델이 어느 시점 이야기인지 헷갈린다.
    if doc.quarterly is not None and doc.quarterly_sections is not None:
        mdna_body = doc.quarterly_sections.mdna
        mdna_label = f"10-Q Item 2 경영진 논의·분석 ({doc.quarterly.filing_date} 제출 · 최신 분기)"
        parts.insert(
            2,
            f"최신 분기보고서: 10-Q · {doc.quarterly.filing_date} 제출"
            " — 경영진 논의는 이 분기 것을 싣습니다.",
        )
    else:
        mdna_body = sections.mdna
        mdna_label = "Item 7 경영진 논의·분석"

    for tag, label, body in (
        ("item_1_business", "Item 1 사업", sections.business),
        ("item_1a_risk_factors", "Item 1A 위험요인", sections.risk_factors),
        ("mdna", mdna_label, mdna_body),
    ):
        if body:
            parts.append(f"<{tag} label=\"{label}\">\n{body}\n</{tag}>\n")

    missing = [
        label
        for label, body in (
            ("Item 1", sections.business),
            ("Item 1A", sections.risk_factors),
            ("경영진 논의", mdna_body),
        )
        if not body
    ]
    if missing:
        # 없는 항목을 밝혀 두지 않으면 모델이 빈 자리를 상상으로 채운다.
        parts.append(
            f"※ 이 문서에서 {', '.join(missing)} 은 본문을 확보하지 못했습니다. "
            "해당 항목에 대해서는 추측하지 말고 확보된 내용만으로 답하십시오."
        )
    if sections.truncated:
        parts.append(
            f"※ {', '.join(sections.truncated)} 은 길이가 길어 앞부분만 실려 있습니다."
        )
    return "\n".join(parts)


def _trim(sections: TenKSections) -> TenKSections:
    """가장 긴 섹션의 뒤 4분의 1을 잘라낸다. 입력 토큰 상한에 걸렸을 때만 쓴다."""
    lengths = {
        "risk_factors": len(sections.risk_factors),
        "mdna": len(sections.mdna),
        "business": len(sections.business),
    }
    longest = max(lengths, key=lambda k: lengths[k])
    body = getattr(sections, longest)
    shortened = body[: int(len(body) * 0.75)].rstrip()
    return TenKSections(
        business=shortened if longest == "business" else sections.business,
        risk_factors=shortened if longest == "risk_factors" else sections.risk_factors,
        mdna=shortened if longest == "mdna" else sections.mdna,
        truncated=tuple(sorted(set(sections.truncated) | {_LABELS[longest]})),
        mdna_from_reference=sections.mdna_from_reference,
    )


_LABELS = {"business": "Item 1", "risk_factors": "Item 1A", "mdna": "Item 7"}


# ---------------------------------------------------------------- DB 조회


def _client() -> anthropic.AsyncAnthropic:
    # 동기 클라이언트를 쓰면 uvicorn 워커 하나가 호출 내내 통째로 막힌다.
    return anthropic.AsyncAnthropic(api_key=get_settings().require("anthropic_api_key"))


def load(ticker: str) -> SecAnalysis | None:
    """이 티커의 최신 분석 결과. 현재 모델·프롬프트 버전 기준."""
    with get_session() as session:
        return session.execute(
            select(SecAnalysis)
            .where(
                SecAnalysis.ticker == ticker.strip().upper(),
                SecAnalysis.model == MODEL,
                SecAnalysis.prompt_version == PROMPT_VERSION,
            )
            .order_by(SecAnalysis.fiscal_year.desc())
            .limit(1)
        ).scalar_one_or_none()


def _find(accession_no: str) -> SecAnalysis | None:
    with get_session() as session:
        return session.get(SecAnalysis, (accession_no, MODEL, PROMPT_VERSION))


def _save(row: SecAnalysis) -> SecAnalysis:
    with get_session() as session:
        merged = session.merge(row)
        session.commit()
        session.refresh(merged)
        session.expunge(merged)
        return merged


def _failed_row(doc: _Document, message: str) -> SecAnalysis:
    return SecAnalysis(
        accession_no=doc.filing.accession_no,
        model=MODEL,
        prompt_version=PROMPT_VERSION,
        cik=doc.company.cik,
        ticker=doc.company.ticker,
        fiscal_year=doc.fiscal_year,
        period_end=doc.filing.report_date or "",
        filed_date=doc.filing.filing_date,
        source_url=doc.filing.viewer_url,
        status=STATUS_FAILED,
        error=message,
    )


# ---------------------------------------------------------------- 본체


async def _latest_filings(company: SecCompany) -> tuple[UsFiling, UsFiling | None]:
    """최신 10-K 와 최신 10-Q 를 **제출목록 한 번**으로 함께 뽑는다.

    따로 부르면 같은 목록을 두 번 받는다. SEC 는 초당 상한이 빡빡해서 아낄 이유가 있다.
    10-Q 는 없을 수 있다 — 회계연도 4분기 자리에는 내지 않고, 신규 상장사는 아직 없다.
    """
    async with SecClient() as sec:
        submissions = await sec.get_submissions(company.cik)
    annual = SecClient.parse_filings(submissions, forms=("10-K", "10-K/A"), limit=1)
    if not annual:
        raise AnalysisError(
            f"'{company.ticker}' 의 10-K 를 찾지 못했습니다.\n"
            "10-K 를 내지 않는 외국 발행사(20-F 제출)이거나 신규 상장일 수 있습니다."
        )
    quarterly = SecClient.parse_filings(submissions, forms=("10-Q",), limit=1)
    return annual[0], (quarterly[0] if quarterly else None)


async def _fetch_10q_sections(filing: UsFiling) -> TenQSections:
    async with SecClient() as sec:
        html = await sec.get_filing_document(filing)
    text = await asyncio.to_thread(html_to_text, html)
    return await asyncio.to_thread(extract_10q_sections, text)


async def _fetch_quarterly(
    company: SecCompany, filing: UsFiling | None
) -> tuple[UsFiling, TenQSections] | None:
    """최신 10-Q 와 그 안의 MD&A. **실패해도 분석을 멈추지 않는다.**

    이것은 신선도를 더하는 곁가지다. 연차보고서만으로도 카드는 완성된다 —
    여기서 예외가 새어 나가면 곁가지 때문에 본체가 죽는다(조사 문서 B-4 와 같은 규칙).
    """
    if filing is None:
        return None
    try:
        sections = await _fetch_10q_sections(filing)
    except (SecError, TenKExtractError, AnalysisError) as exc:
        logger.warning("%s 10-Q 를 읽지 못해 연차보고서만으로 분석합니다: %s", company.ticker, exc)
        return None
    if not sections.mdna:
        return None
    return filing, sections


async def _fetch_sections(filing: UsFiling) -> TenKSections:
    async with SecClient() as sec:
        html = await sec.get_filing_document(filing)
    # 태그 제거는 CPU 작업이다. 12MB 문서면 1~2초 걸려 이벤트 루프를 막는다.
    text = await asyncio.to_thread(html_to_text, html)
    sections = await asyncio.to_thread(extract_sections, text)
    if sections.is_empty:
        raise TenKExtractError(
            "본문에서 Item 1·1A·7 을 찾지 못했습니다.\n"
            "  항목 표기가 일반적이지 않은 문서일 수 있습니다. 원문 링크로 직접 확인해 주세요."
        )
    return sections


async def _fit_prompt(
    client: anthropic.AsyncAnthropic, doc: _Document
) -> tuple[str, TenKSections, int]:
    """입력 상한 안에 들어오는 프롬프트를 만든다. (프롬프트, 쓴 섹션, 토큰 수)

    동기 호출과 배치 제출이 **같은 프롬프트를 써야** 결과를 견줄 수 있으므로 여기 모았다.
    `count_tokens` 는 무료라 잘라내기를 몇 번 돌려도 돈이 들지 않는다.
    """
    sections = doc.sections
    prompt = _build_prompt(doc, sections)

    for _ in range(TRIM_ATTEMPTS):
        counted = await client.messages.count_tokens(  # 무료
            model=MODEL,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        if counted.input_tokens <= MAX_INPUT_TOKENS:
            return prompt, sections, counted.input_tokens
        logger.warning(
            "입력이 상한을 넘어 잘라냅니다: %d > %d", counted.input_tokens, MAX_INPUT_TOKENS
        )
        sections = _trim(sections)
        prompt = _build_prompt(doc, sections)

    raise AnalysisError(
        "본문이 너무 길어 상한 안으로 줄이지 못했습니다. 분석하지 않았습니다."
    )


async def _call_model(
    client: anthropic.AsyncAnthropic, doc: _Document
) -> tuple[TenKAnalysisContent, TenKSections, int, int]:
    """입력 상한을 지킨 뒤 한 번 호출한다."""
    prompt, sections, _ = await _fit_prompt(client, doc)

    response = await client.messages.parse(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": prompt}],
        output_format=TenKAnalysisContent,
    )

    if response.stop_reason == "refusal":
        raise AnalysisError(
            "안전 정책에 따라 이 문서의 분석이 거절되었습니다. 원문 링크로 확인해 주세요."
        )
    if response.parsed_output is None:
        raise AnalysisError(
            "분석 결과를 정해진 형식으로 받지 못했습니다. 잠시 뒤 다시 시도해 주세요."
            f" (종료 사유: {response.stop_reason})"
        )

    # 형식은 맞는데 알맹이가 빈 응답을 걸러낸다. 이걸 저장해 버리면 캐시가 영원히
    # 껍데기를 돌려주고, 사용자는 다시 시도할 방법이 없다 — 캐시가 독이 되는 경우다.
    if not _is_complete(response.parsed_output):
        raise AnalysisError(
            "분석 결과가 비어 있어 저장하지 않았습니다. 다시 시도해 주세요."
        )

    return (
        response.parsed_output,
        sections,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )


def _is_complete(content: TenKAnalysisContent) -> bool:
    """알맹이가 들어 있는 응답인지.

    한 문장 요약·사업 요약·위험요인 셋이 다 있어야 분석이라 부를 만하다. 경영진 논의는
    문서에 따라 참조 형식뿐일 수 있으므로 필수로 두지 않는다.

    `one_liner` 를 여기 넣은 이유: 그것이 카드 맨 위에 크게 놓이는 심장이라, 비면 화면이
    머리 없는 카드가 된다. v2 에서 실제로 겪은 "다섯 필드 중 하나만 채우는" 실패가
    이 자리에서 걸려야 한다.
    """
    return (
        bool(content.one_liner.strip())
        and bool(content.business_summary.strip())
        and bool(content.key_risks)
    )


async def analyze(company: SecCompany, *, force: bool = False) -> SecAnalysis:
    """최신 10-K 를 분석한다. 이미 있으면 그대로 돌려주고 API 를 부르지 않는다."""
    # 10-K 와 최신 10-Q 를 함께 잡는다. 분기가 바뀌었으면 카드를 다시 만들 값어치가
    # 있으므로, 캐시를 볼 때 그 판단에 쓴다.
    filing, quarterly_filing = await _latest_filings(company)
    quarterly_accession = quarterly_filing.accession_no if quarterly_filing else ""

    existing = _find(filing.accession_no)
    if existing is not None and not _should_rerun(
        existing, force=force, quarterly_accession=quarterly_accession
    ):
        return existing

    async with llm_budget.call_lock:
        # 잠금을 기다리는 사이 다른 요청이 이미 끝냈을 수 있다.
        existing = _find(filing.accession_no)
        if existing is not None and not _should_rerun(
        existing, force=force, quarterly_accession=quarterly_accession
    ):
            return existing

        try:
            llm_budget.check_daily_limit()
        except llm_budget.BudgetExceeded as exc:
            raise AnalysisError(str(exc)) from exc

        doc_stub = _Document(company=company, filing=filing, sections=_EMPTY)
        try:
            sections = await _fetch_sections(filing)
        except (SecError, TenKExtractError) as exc:
            # 여기까지는 돈이 들지 않았다. 실패를 남기되 다음 요청에서 다시 시도된다.
            return _save(_failed_row(doc_stub, str(exc)))

        # 최신 분기(10-Q)의 경영진 논의를 곁들인다. 못 읽어도 분석은 그대로 진행된다.
        quarterly = await _fetch_quarterly(company, quarterly_filing)
        doc = _Document(
            company=company,
            filing=filing,
            sections=sections,
            quarterly=quarterly[0] if quarterly else None,
            quarterly_sections=quarterly[1] if quarterly else None,
        )
        client = _client()
        try:
            content, used_sections, in_tok, out_tok = await _call_model(client, doc)
        except AnalysisError as exc:
            return _save(_failed_row(doc, str(exc)))
        except anthropic.APIStatusError as exc:
            return _save(_failed_row(doc, f"Anthropic API 오류 (HTTP {exc.status_code}): {exc.message}"))
        except anthropic.APIConnectionError:
            return _save(_failed_row(doc, "Anthropic 서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요."))
        finally:
            await client.close()

        row = SecAnalysis(
            accession_no=filing.accession_no,
            model=MODEL,
            prompt_version=PROMPT_VERSION,
            cik=company.cik,
            ticker=company.ticker,
            fiscal_year=doc.fiscal_year,
            period_end=filing.report_date or "",
            filed_date=filing.filing_date,
            source_url=filing.viewer_url,
            content_json=content.model_dump_json(),
            sections=",".join(used_sections.found),
            quarterly_accession=doc.quarterly.accession_no if doc.quarterly else "",
            quarterly_filed_date=doc.quarterly.filing_date if doc.quarterly else "",
            truncated=",".join(used_sections.truncated),
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_micro_usd=llm_budget.cost_micro_usd(in_tok, out_tok),
            status=STATUS_OK,
        )
        saved = _save(row)
        logger.info(
            "10-K 분석 완료: %s FY%d · 입력 %d · 출력 %d · 추정 $%.3f",
            saved.ticker,
            saved.fiscal_year,
            in_tok,
            out_tok,
            saved.cost_usd,
        )
        return saved


_EMPTY = TenKSections(business="", risk_factors="", mdna="")


def _should_rerun(
    row: SecAnalysis, *, force: bool, quarterly_accession: str | None = None
) -> bool:
    """저장된 행이 있는데도 다시 부를지.

    성공한 분석은 force 여도 다시 부르지 않는다 — 같은 10-K 를 다시 분석해 얻는 것이
    없고 돈만 든다. 프롬프트를 고쳤으면 PROMPT_VERSION 을 올리는 것이 올바른 방법이다.

    **예외가 하나 생겼다(2026-09-06).** 경영진 논의를 최신 10-Q 에서 가져오게 되면서,
    같은 10-K 라도 그 뒤에 새 분기보고서가 나왔으면 카드가 낡은 것이 된다. 그때는
    다시 분석할 값어치가 있다 — 얻는 것이 있기 때문이다.

    이 문은 열되 돈은 기존 울타리가 막는다. 자동 분석은 관심종목만, 하루 상한 안에서,
    사람 몫 5건을 남기고, 반값 배치로 간다(`auto_analysis.py`).
    """
    if row.status == STATUS_OK:
        if (
            quarterly_accession is not None
            and quarterly_accession != ""
            and quarterly_accession != row.quarterly_accession
        ):
            return True
        return False
    # 배치에 맡겨 두고 기다리는 중이면 건드리지 않는다. 다시 부르면 같은 문서를 두 번
    # 사는 것이고, 곧 도착할 결과가 이 행을 덮어쓴다.
    if row.status == STATUS_PENDING:
        return False
    # 돈을 쓰지 않고 실패한 것(원문 내려받기·추출 실패)은 공짜로 다시 시도한다.
    if row.input_tokens == 0:
        return True
    return force


# ---------------------------------------------------------------- 배치 경로
#
# 밤에 도는 자동 분석만 이 길로 간다. **모든 토큰이 반값**인 대신 결과가 최대 24시간
# 뒤에 온다(`analysis_batch.py` 참고). 사람이 "분석하기"를 누른 경우는 위의 동기 경로다.
#
# 두 단계로 나뉜다:
#   prepare_batch()  문서를 받아 프롬프트를 만들고 **대기 행을 저장한 뒤** 요청을 돌려준다
#   apply_outcome()  결과가 오면 그 대기 행을 덮어쓴다
#
# 대기 행을 미리 저장하는 이유가 셋이다 — 하루 상한이 제출한 건수를 세고, 같은 문서를
# 두 번 맡기지 않으며, 화면이 "분석 중"을 보여줄 수 있다.

#: 배치 요청 하나를 우리 행과 잇는 이름표. 국내(`kr:`)와 한 배치에 섞여 들어간다.
CUSTOM_ID_PREFIX = "us:"


def custom_id_for(accession_no: str) -> str:
    return f"{CUSTOM_ID_PREFIX}{accession_no}"


async def prepare_batch(company: SecCompany) -> object | None:
    """자동 분석용 배치 요청 한 건. 맡길 것이 없으면 None.

    돈이 드는 단계 직전까지 여기서 다 한다 — 최신 보고서 찾기, 원문 받기, 항목 추출,
    프롬프트 길이 맞추기. 실패하면 그 이유를 행으로 남기고 None 을 돌려준다(동기 경로와 같다).
    """
    # 10-K 와 최신 10-Q 를 함께 잡는다. 분기가 바뀌었으면 카드를 다시 만들 값어치가
    # 있으므로, 캐시를 볼 때 그 판단에 쓴다.
    filing, quarterly_filing = await _latest_filings(company)
    quarterly_accession = quarterly_filing.accession_no if quarterly_filing else ""

    existing = _find(filing.accession_no)
    if existing is not None and not _should_rerun(
        existing, force=False, quarterly_accession=quarterly_accession
    ):
        return None

    async with llm_budget.call_lock:
        existing = _find(filing.accession_no)
        if existing is not None and not _should_rerun(
        existing, force=False, quarterly_accession=quarterly_accession
    ):
            return None

        try:
            llm_budget.check_daily_limit()
        except llm_budget.BudgetExceeded as exc:
            raise AnalysisError(str(exc)) from exc

        doc_stub = _Document(company=company, filing=filing, sections=_EMPTY)
        try:
            sections = await _fetch_sections(filing)
        except (SecError, TenKExtractError) as exc:
            _save(_failed_row(doc_stub, str(exc)))
            return None

        # 최신 분기(10-Q)의 경영진 논의를 곁들인다. 못 읽어도 분석은 그대로 진행된다.
        quarterly = await _fetch_quarterly(company, quarterly_filing)
        doc = _Document(
            company=company,
            filing=filing,
            sections=sections,
            quarterly=quarterly[0] if quarterly else None,
            quarterly_sections=quarterly[1] if quarterly else None,
        )
        client = _client()
        try:
            prompt, used_sections, in_tok = await _fit_prompt(client, doc)
        except AnalysisError as exc:
            _save(_failed_row(doc, str(exc)))
            return None
        except anthropic.APIStatusError as exc:
            _save(_failed_row(doc, f"Anthropic API 오류 (HTTP {exc.status_code}): {exc.message}"))
            return None
        except anthropic.APIConnectionError:
            _save(_failed_row(doc, "Anthropic 서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요."))
            return None
        finally:
            await client.close()

        # 대기 행. input_tokens 를 미리 넣는 것은 하루 상한이 이 건을 세게 하려는 것이다.
        # 실제 값은 결과가 오면 덮어쓴다.
        _save(
            SecAnalysis(
                accession_no=filing.accession_no,
                model=MODEL,
                prompt_version=PROMPT_VERSION,
                cik=company.cik,
                ticker=company.ticker,
                fiscal_year=doc.fiscal_year,
                period_end=filing.report_date or "",
                filed_date=filing.filing_date,
                source_url=filing.viewer_url,
                content_json="",
                sections=",".join(used_sections.found),
            quarterly_accession=doc.quarterly.accession_no if doc.quarterly else "",
            quarterly_filed_date=doc.quarterly.filing_date if doc.quarterly else "",
                truncated=",".join(used_sections.truncated),
                input_tokens=in_tok,
                output_tokens=0,
                cost_micro_usd=0,
                status=STATUS_PENDING,
                error="",
            )
        )

        return analysis_batch.build_request(
            custom_id=custom_id_for(filing.accession_no),
            model=MODEL,
            system=SYSTEM_PROMPT,
            prompt=prompt,
            output_model=TenKAnalysisContent,
            max_tokens=MAX_OUTPUT_TOKENS,
            effort=EFFORT,
        )


def mark_submitted(accession_no: str, batch_id: str) -> None:
    """대기 행에 배치 id 를 적는다. 제출이 끝난 뒤에만 부른다."""
    with get_session() as session:
        row = session.get(SecAnalysis, (accession_no, MODEL, PROMPT_VERSION))
        if row is not None:
            row.batch_id = batch_id
            session.commit()


def pending_batch_ids() -> list[str]:
    """결과를 기다리는 배치 id 들."""
    with get_session() as session:
        return list(
            session.execute(
                select(SecAnalysis.batch_id)
                .where(SecAnalysis.status == STATUS_PENDING, SecAnalysis.batch_id != "")
                .distinct()
            ).scalars()
        )


def apply_outcome(outcome: analysis_batch.Outcome) -> bool:
    """배치 결과 한 건을 대기 행에 덮어쓴다. 우리 행이 아니면 False.

    성공이든 실패든 **행을 남긴다.** 지우면 다음 자동 분석이 같은 문서를 또 맡긴다.
    """
    if not outcome.custom_id.startswith(CUSTOM_ID_PREFIX):
        return False
    accession_no = outcome.custom_id[len(CUSTOM_ID_PREFIX) :]

    with get_session() as session:
        row = session.get(SecAnalysis, (accession_no, MODEL, PROMPT_VERSION))
        if row is None:
            logger.warning("배치 결과에 맞는 행이 없다: %s", outcome.custom_id)
            return False

        row.input_tokens = outcome.input_tokens or row.input_tokens
        row.output_tokens = outcome.output_tokens
        row.cost_micro_usd = llm_budget.cost_micro_usd(
            row.input_tokens, outcome.output_tokens, batch=True
        )

        # 실패 이유를 하나씩 좁혀 간다. 마지막까지 None 이면 성공이다.
        # **어느 갈래로 빠지든 마지막에 한 번 커밋한다** — 갈래마다 커밋을 흩어 놓으면
        # 하나를 빠뜨렸을 때 그 경우만 조용히 저장되지 않는다(실제로 한 번 그랬다).
        failure: str | None = None
        content = None

        if not outcome.ok:
            failure = outcome.error or "배치 처리에 실패했습니다."
        else:
            try:
                content = analysis_batch.parse_content(outcome.text or "", TenKAnalysisContent)
            except Exception as exc:  # noqa: BLE001 — 어떤 형식 오류든 행으로 남긴다
                failure = f"분석 결과를 정해진 형식으로 받지 못했습니다: {type(exc).__name__}"

        # 동기 경로와 같은 검사. 껍데기를 저장하면 캐시가 영원히 껍데기를 돌려준다.
        if failure is None and content is not None and not _is_complete(content):
            failure = "분석 결과가 비어 있어 저장하지 않았습니다."

        if failure is not None:
            row.status = STATUS_FAILED
            row.error = failure
        else:
            row.content_json = content.model_dump_json()  # type: ignore[union-attr]
            row.status = STATUS_OK
            row.error = ""
            logger.info(
                "10-K 배치 분석 완료: %s FY%d · 입력 %d · 출력 %d · 추정 $%.3f",
                row.ticker,
            row.fiscal_year,
                row.input_tokens,
                row.output_tokens,
                row.cost_micro_usd / 1_000_000,
            )

        session.commit()
        return True
