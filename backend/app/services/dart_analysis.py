"""사업보고서 서술 분석 — DART 원문을 받아 Claude 에 보내고 결과를 저장한다.

미국 `tenk_analysis.py` 의 국내판이다. 비용 상한은 `llm_budget.py` 에서 두 시장이
함께 쓴다 — 상한은 지갑 기준이지 시장 기준이 아니다.

**국내 서식이 미국과 다른 점이 분석 설계에 그대로 영향을 준다.**

10-K 에는 Item 1A(위험요인)가 독립 항목으로 있어 "회사가 스스로 꼽은 위험" 목록을
그대로 받을 수 있다. **국내 사업보고서에는 그런 항목이 없다.** 위험은 여기저기 흩어져 있다:

  - II-5. 위험관리 및 파생거래      (사업의 내용 안)
  - XI. 그 밖에 투자자 보호를 위하여 필요한 사항  (소송·제재·우발부채)

그래서 XI 를 따로 뽑아 함께 보내고, 프롬프트에서 "목록으로 정리돼 있지 않으니 본문에서
찾아내라"고 명시한다. 흩어진 것을 모아 주는 것이 국내판의 값어치다.

**숫자는 LLM 이 만들지 않는다**(CLAUDE.md 절대 규칙 3). 응답 스키마에 수치 필드를 두지
않아 끼워 넣을 자리가 없고, 프롬프트에서도 금지한다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.clients.dart import DartClient, DartError, Disclosure
from app.config import get_settings
from app.models.base import get_session
from app.models.corp import DartCorp
from app.models.dart_analysis import (
    STATUS_FAILED,
    STATUS_OK,
    STATUS_PENDING,
    DartAnalysis,
)
from app.services import analysis_batch, llm_budget
from app.services.dart_extract import (
    DartExtractError,
    ReportSections,
    extract_sections,
    is_annual_report,
    main_document,
)

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
# 프롬프트·스키마·effort 를 고치면 올린다. 옛 결과를 지우지 않고 새로 분석된다.
PROMPT_VERSION = 1

MAX_OUTPUT_TOKENS = 16_000
MAX_INPUT_TOKENS = 180_000
TRIM_ATTEMPTS = 3
# medium 으로 두면 모델이 첫 필드만 채우고 끝내는 일이 있다(미국 쪽에서 MSFT 가 그랬다).
# 몇 초 더 걸리는 대신 다섯 필드를 제대로 채운다. 낮추지 말 것.
EFFORT = "high"

# 사업보고서를 찾을 때 거슬러 올라가는 기간과, 원문 받기를 시도할 후보 수.
LOOKBACK_YEARS = 2
MAX_CANDIDATES = 3


class AnalysisError(Exception):
    """분석을 진행할 수 없음. 메시지를 그대로 화면에 보여줄 수 있게 쓴다."""


# ---------------------------------------------------------------- 응답 스키마


class RiskItem(BaseModel):
    title: str = Field(description="위험을 한 줄로. 예: '중국 매출 의존'")
    why_it_matters: str = Field(
        description="이 위험이 이 회사에 왜 실질적인지 2~3문장. 수치는 쓰지 않는다."
    )
    source: str = Field(
        description=(
            "보고서 어디에서 나온 내용인지. 예: '위험관리 및 파생거래', "
            "'투자자 보호사항 - 제재', '사업의 내용'"
        )
    )


class ReportAnalysisContent(BaseModel):
    """사업보고서 서술 분석 결과. **수치 필드가 하나도 없다.**"""

    business_summary: str = Field(
        description="이 회사가 무엇을 팔아 돈을 버는지 3~5문장"
    )
    segments: list[str] = Field(
        description="사업 부문별 한 줄 설명. 부문 구분이 없으면 빈 목록"
    )
    key_risks: list[RiskItem] = Field(
        description=(
            "보고서 곳곳에서 찾아낸 실질적 위험 최대 6건. "
            "형식적 문구가 아니라 이 회사에 특유한 것만"
        )
    )
    mdna_points: list[str] = Field(
        description="경영진이 실적·전망의 근거로 든 것. 수치 없이 이유만"
    )
    moat_and_competition: str = Field(
        description="경쟁 구도와 회사가 주장하는 우위. 근거가 없으면 그렇게 쓴다"
    )


SYSTEM_PROMPT = """\
당신은 국내 상장사의 사업보고서를 읽고 핵심을 뽑아내는 애널리스트입니다.
읽는 사람은 투자와 공시에 지식이 깊은 금융권 실무자이며, 수백 쪽을 직접 읽을 시간이 없습니다.

지켜야 할 규칙:

1. **어떤 수치도 쓰지 마십시오.** 금액·성장률·비율·점유율·주가·인원수를 문장에 넣지
   않습니다. "매출이 늘었다"는 되고 "매출이 12% 늘었다"는 안 됩니다. 수치는 별도의
   재무표로 제공되며, 당신의 역할은 문장 해석뿐입니다. 이것이 가장 중요한 규칙입니다.
2. **원문에 없는 것을 쓰지 마십시오.** 배경지식으로 보충하거나 추론해서 채우지 않습니다.
   보고서에 근거가 없으면 "보고서에 명시되어 있지 않다"고 쓰십시오.
3. **투자 의견을 쓰지 마십시오.** 매수·매도·목표주가·저평가 판단을 하지 않습니다.
4. **위험요인은 직접 찾아내야 합니다.** 국내 사업보고서에는 미국 10-K 의 「위험요인」처럼
   위험만 모아 둔 항목이 없습니다. 대신 「위험관리 및 파생거래」, 「투자자 보호를 위하여
   필요한 사항」의 소송·제재·우발부채, 그리고 사업 서술 안에 흩어져 있습니다.
   그것들을 읽고 **이 회사에 실질적으로 중요한 것**을 골라내십시오.
   "환율이 변동할 수 있다" 같은 어느 회사에나 해당하는 일반론은 넣지 마십시오.
   각 위험이 보고서 어디에서 나왔는지 `source` 에 적으십시오.
5. 사업보고서는 홍보성 표현이 섞여 있습니다("업계 최고 수준의", "혁신적인").
   그대로 옮기지 말고 사실만 남기십시오.
6. 문장은 간결하게. 원문을 그대로 베끼지 말고 뜻을 풀어 쓰십시오.
"""


# ---------------------------------------------------------------- 문서 찾기


@dataclass(frozen=True)
class _Report:
    corp: DartCorp
    disclosure: Disclosure
    sections: ReportSections

    @property
    def fiscal_year(self) -> int:
        """보고서 이름의 "(2025.12)" 에서 회계연도를 읽는다.

        접수일로 추정하면 어긋난다 — 3월에 접수된 것이 전년도 보고서다.
        """
        import re

        match = re.search(r"\((\d{4})\.\d{2}\)", self.disclosure.report_name)
        if match:
            return int(match.group(1))
        # 이름에 없으면 접수 연도에서 1을 뺀다. 사업보고서는 결산 후 3개월 안에 낸다.
        try:
            return int(self.disclosure.received_date[:4]) - 1
        except (ValueError, IndexError):
            return 0


async def _annual_candidates(corp: DartCorp) -> list[Disclosure]:
    """최신 사업보고서 후보를 최신순으로.

    `final_only=False` 로 보는 이유: 최신 정정본의 원문 파일이 없는 경우가 있다
    (KB금융이 그랬다 — status 014). 그때 이전 판으로 물러설 수 있어야 한다.
    정정본이 먼저 오므로 순서대로 시도하면 가장 정확한 판부터 잡힌다.
    """
    async with DartClient() as dart:
        items = await dart.get_disclosures(
            corp.corp_code,
            begin=date(date.today().year - LOOKBACK_YEARS, 1, 1),
            end=date.today(),
            count=100,
            report_type="A",  # 정기공시
            final_only=False,
        )
    return [d for d in items if is_annual_report(d.report_name)][:MAX_CANDIDATES]


async def _fetch_sections(candidates: list[Disclosure]) -> tuple[Disclosure, ReportSections]:
    """후보를 순서대로 시도해 첫 번째로 읽히는 것을 쓴다."""
    problems: list[str] = []
    for disclosure in candidates:
        try:
            async with DartClient() as dart:
                documents = await dart.get_document(disclosure.receipt_no)
            body = main_document(documents, disclosure.receipt_no)
            # 수 MB 문서의 태그 제거는 CPU 작업이다. 이벤트 루프를 막지 않는다.
            sections = await asyncio.to_thread(extract_sections, body)
        except (DartError, DartExtractError) as exc:
            problems.append(f"{disclosure.received_date} {disclosure.report_name}: {exc}")
            continue
        if not sections.is_empty:
            return disclosure, sections
        problems.append(f"{disclosure.received_date} {disclosure.report_name}: 절을 찾지 못함")

    raise AnalysisError(
        "사업보고서 원문을 읽지 못했습니다.\n  " + "\n  ".join(problems[:3])
    )


# ---------------------------------------------------------------- 프롬프트


def _build_prompt(report: _Report, sections: ReportSections) -> str:
    parts = [
        f"회사: {report.corp.corp_name} ({report.corp.stock_code})",
        f"보고서: {report.disclosure.report_name} · {report.disclosure.received_date} 접수",
        "",
    ]
    for tag, label, body in (
        ("사업의_내용", "II. 사업의 내용", sections.business),
        ("경영진단", "IV. 이사의 경영진단 및 분석의견", sections.mdna),
        ("투자자_보호사항", "XI. 그 밖에 투자자 보호를 위하여 필요한 사항", sections.investor),
    ):
        if body:
            parts.append(f"<{tag} label=\"{label}\">\n{body}\n</{tag}>\n")

    missing = [
        label
        for label, body in (
            ("사업의 내용", sections.business),
            ("경영진단", sections.mdna),
            ("투자자 보호사항", sections.investor),
        )
        if not body
    ]
    if missing:
        # 없는 절을 밝히지 않으면 모델이 빈 자리를 상상으로 채운다.
        parts.append(
            f"※ 이 보고서에서 {', '.join(missing)} 은 확보하지 못했습니다. "
            "추측하지 말고 확보된 내용만으로 답하십시오."
        )
    if sections.truncated:
        parts.append(f"※ {', '.join(sections.truncated)} 은 분량이 많아 앞부분만 실려 있습니다.")
    return "\n".join(parts)


_LABELS = {"business": "사업의 내용", "mdna": "경영진단", "investor": "투자자 보호사항"}


def _trim(sections: ReportSections) -> ReportSections:
    """가장 긴 절의 뒤 4분의 1을 잘라낸다. 입력 상한에 걸렸을 때만 쓴다."""
    lengths = {
        "business": len(sections.business),
        "investor": len(sections.investor),
        "mdna": len(sections.mdna),
    }
    longest = max(lengths, key=lambda k: lengths[k])
    body = getattr(sections, longest)
    shortened = body[: int(len(body) * 0.75)].rstrip()
    return ReportSections(
        business=shortened if longest == "business" else sections.business,
        mdna=shortened if longest == "mdna" else sections.mdna,
        investor=shortened if longest == "investor" else sections.investor,
        truncated=tuple(sorted(set(sections.truncated) | {_LABELS[longest]})),
    )


# ---------------------------------------------------------------- DB


def _client() -> anthropic.AsyncAnthropic:
    # 동기 클라이언트면 uvicorn 워커 하나가 호출 내내 막힌다.
    return anthropic.AsyncAnthropic(api_key=get_settings().require("anthropic_api_key"))


def load(stock_code: str) -> DartAnalysis | None:
    """이 종목의 최신 분석 결과. 현재 모델·프롬프트 버전 기준."""
    with get_session() as session:
        return session.execute(
            select(DartAnalysis)
            .where(
                DartAnalysis.stock_code == stock_code.strip(),
                DartAnalysis.model == MODEL,
                DartAnalysis.prompt_version == PROMPT_VERSION,
            )
            .order_by(DartAnalysis.fiscal_year.desc(), DartAnalysis.received_date.desc())
            .limit(1)
        ).scalar_one_or_none()


def _find(receipt_no: str) -> DartAnalysis | None:
    with get_session() as session:
        return session.get(DartAnalysis, (receipt_no, MODEL, PROMPT_VERSION))


def _save(row: DartAnalysis) -> DartAnalysis:
    with get_session() as session:
        merged = session.merge(row)
        session.commit()
        session.refresh(merged)
        session.expunge(merged)
        return merged


def _failed_row(corp: DartCorp, disclosure: Disclosure | None, message: str) -> DartAnalysis:
    return DartAnalysis(
        receipt_no=disclosure.receipt_no if disclosure else f"NONE-{corp.corp_code}",
        model=MODEL,
        prompt_version=PROMPT_VERSION,
        corp_code=corp.corp_code,
        stock_code=corp.stock_code,
        corp_name=corp.corp_name,
        report_name=disclosure.report_name if disclosure else "",
        received_date=disclosure.received_date if disclosure else "",
        source_url=disclosure.viewer_url if disclosure else "",
        status=STATUS_FAILED,
        error=message,
    )


def _is_complete(content: ReportAnalysisContent) -> bool:
    """알맹이가 든 응답인지. 껍데기를 저장하면 캐시가 영원히 그것을 돌려준다."""
    return bool(content.business_summary.strip()) and bool(content.key_risks)


# ---------------------------------------------------------------- 본체


async def _fit_prompt(
    client: anthropic.AsyncAnthropic, report: _Report
) -> tuple[str, ReportSections, int]:
    """입력 상한 안에 들어오는 프롬프트를 만든다. (프롬프트, 쓴 섹션, 토큰 수)

    동기 호출과 배치 제출이 **같은 프롬프트를 써야** 결과를 견줄 수 있으므로 여기 모았다.
    `count_tokens` 는 무료라 잘라내기를 몇 번 돌려도 돈이 들지 않는다.
    """
    sections = report.sections
    prompt = _build_prompt(report, sections)

    for _ in range(TRIM_ATTEMPTS):
        counted = await client.messages.count_tokens(  # 무료
            model=MODEL,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        if counted.input_tokens <= MAX_INPUT_TOKENS:
            return prompt, sections, counted.input_tokens
        logger.warning("입력이 상한을 넘어 잘라냅니다: %d", counted.input_tokens)
        sections = _trim(sections)
        prompt = _build_prompt(report, sections)

    raise AnalysisError("본문이 너무 길어 상한 안으로 줄이지 못했습니다.")


async def _call_model(
    client: anthropic.AsyncAnthropic, report: _Report
) -> tuple[ReportAnalysisContent, ReportSections, int, int]:
    prompt, sections, _ = await _fit_prompt(client, report)

    response = await client.messages.parse(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": prompt}],
        output_format=ReportAnalysisContent,
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
    if not _is_complete(response.parsed_output):
        raise AnalysisError("분석 결과가 비어 있어 저장하지 않았습니다. 다시 시도해 주세요.")

    return (
        response.parsed_output,
        sections,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )


def _should_rerun(row: DartAnalysis, *, force: bool) -> bool:
    """저장된 행이 있는데도 다시 부를지.

    성공한 분석은 force 여도 다시 부르지 않는다 — 같은 문서를 다시 분석해 얻는 것이
    없고 돈만 든다. 프롬프트를 고쳤으면 PROMPT_VERSION 을 올리는 것이 올바른 방법이다.
    """
    if row.status == STATUS_OK:
        return False
    # 배치에 맡겨 두고 기다리는 중이면 건드리지 않는다. 다시 부르면 같은 문서를 두 번
    # 사는 것이고, 곧 도착할 결과가 이 행을 덮어쓴다.
    if row.status == STATUS_PENDING:
        return False
    if row.input_tokens == 0:
        return True  # 돈을 쓰지 않고 실패한 것은 공짜로 다시 시도한다
    return force


async def analyze(corp: DartCorp, *, force: bool = False) -> DartAnalysis:
    """최신 사업보고서를 분석한다. 이미 있으면 그대로 돌려주고 API 를 부르지 않는다."""
    try:
        candidates = await _annual_candidates(corp)
    except DartError as exc:
        raise AnalysisError(str(exc)) from exc

    if not candidates:
        raise AnalysisError(
            f"'{corp.corp_name}' 의 최근 사업보고서를 찾지 못했습니다.\n"
            "신규 상장이거나 결산기가 달라 아직 제출하지 않았을 수 있습니다."
        )

    # 후보 중 하나라도 이미 분석돼 있으면 그대로 쓴다. 원문을 받기 전에 확인해
    # 수 MB 다운로드를 아낀다.
    for disclosure in candidates:
        existing = _find(disclosure.receipt_no)
        if existing is not None and not _should_rerun(existing, force=force):
            return existing

    async with llm_budget.call_lock:
        for disclosure in candidates:
            existing = _find(disclosure.receipt_no)
            if existing is not None and not _should_rerun(existing, force=force):
                return existing

        try:
            llm_budget.check_daily_limit()
        except llm_budget.BudgetExceeded as exc:
            raise AnalysisError(str(exc)) from exc

        try:
            disclosure, sections = await _fetch_sections(candidates)
        except AnalysisError as exc:
            # 여기까지는 돈이 들지 않았다. 실패를 남기되 다음 요청에서 다시 시도된다.
            return _save(_failed_row(corp, candidates[0], str(exc)))

        report = _Report(corp=corp, disclosure=disclosure, sections=sections)
        client = _client()
        try:
            content, used, in_tok, out_tok = await _call_model(client, report)
        except AnalysisError as exc:
            return _save(_failed_row(corp, disclosure, str(exc)))
        except anthropic.APIStatusError as exc:
            return _save(
                _failed_row(corp, disclosure, f"Anthropic API 오류 (HTTP {exc.status_code}): {exc.message}")
            )
        except anthropic.APIConnectionError:
            return _save(
                _failed_row(corp, disclosure, "Anthropic 서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
            )
        finally:
            await client.close()

        row = DartAnalysis(
            receipt_no=disclosure.receipt_no,
            model=MODEL,
            prompt_version=PROMPT_VERSION,
            corp_code=corp.corp_code,
            stock_code=corp.stock_code,
            corp_name=corp.corp_name,
            report_name=disclosure.report_name,
            fiscal_year=report.fiscal_year,
            received_date=disclosure.received_date,
            source_url=disclosure.viewer_url,
            content_json=content.model_dump_json(),
            sections=",".join(used.found),
            truncated=",".join(used.truncated),
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_micro_usd=llm_budget.cost_micro_usd(in_tok, out_tok),
            status=STATUS_OK,
        )
        saved = _save(row)
        logger.info(
            "사업보고서 분석 완료: %s FY%d · 입력 %d · 출력 %d · 추정 $%.3f",
            saved.corp_name,
            saved.fiscal_year,
            in_tok,
            out_tok,
            saved.cost_usd,
        )
        return saved


# ---------------------------------------------------------------- 배치 경로
#
# 미국(`tenk_analysis.py`)과 같은 짜임이다. 밤에 도는 자동 분석만 이 길로 가고,
# 사람이 누른 경우는 위의 동기 경로다. 자세한 이유는 `analysis_batch.py` 머리말 참고.

#: 배치 요청 하나를 우리 행과 잇는 이름표. 미국(`us:`)과 한 배치에 섞여 들어간다.
CUSTOM_ID_PREFIX = "kr:"


def custom_id_for(receipt_no: str) -> str:
    return f"{CUSTOM_ID_PREFIX}{receipt_no}"


async def prepare_batch(corp: DartCorp) -> object | None:
    """자동 분석용 배치 요청 한 건. 맡길 것이 없으면 None."""
    try:
        candidates = await _annual_candidates(corp)
    except DartError as exc:
        raise AnalysisError(str(exc)) from exc

    if not candidates:
        return None

    existing = _find(candidates[0].receipt_no)
    if existing is not None and not _should_rerun(existing, force=False):
        return None

    async with llm_budget.call_lock:
        existing = _find(candidates[0].receipt_no)
        if existing is not None and not _should_rerun(existing, force=False):
            return None

        try:
            llm_budget.check_daily_limit()
        except llm_budget.BudgetExceeded as exc:
            raise AnalysisError(str(exc)) from exc

        try:
            disclosure, sections = await _fetch_sections(candidates)
        except AnalysisError as exc:
            _save(_failed_row(corp, candidates[0], str(exc)))
            return None

        report = _Report(corp=corp, disclosure=disclosure, sections=sections)
        client = _client()
        try:
            prompt, used, in_tok = await _fit_prompt(client, report)
        except AnalysisError as exc:
            _save(_failed_row(corp, disclosure, str(exc)))
            return None
        except anthropic.APIStatusError as exc:
            _save(
                _failed_row(corp, disclosure, f"Anthropic API 오류 (HTTP {exc.status_code}): {exc.message}")
            )
            return None
        except anthropic.APIConnectionError:
            _save(
                _failed_row(corp, disclosure, "Anthropic 서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
            )
            return None
        finally:
            await client.close()

        # 대기 행. input_tokens 를 미리 넣는 것은 하루 상한이 이 건을 세게 하려는 것이다.
        _save(
            DartAnalysis(
                receipt_no=disclosure.receipt_no,
                model=MODEL,
                prompt_version=PROMPT_VERSION,
                corp_code=corp.corp_code,
                stock_code=corp.stock_code,
                corp_name=corp.corp_name,
                report_name=disclosure.report_name,
                fiscal_year=report.fiscal_year,
                received_date=disclosure.received_date,
                source_url=disclosure.viewer_url,
                content_json="",
                sections=",".join(used.found),
                truncated=",".join(used.truncated),
                input_tokens=in_tok,
                output_tokens=0,
                cost_micro_usd=0,
                status=STATUS_PENDING,
                error="",
            )
        )

        return analysis_batch.build_request(
            custom_id=custom_id_for(disclosure.receipt_no),
            model=MODEL,
            system=SYSTEM_PROMPT,
            prompt=prompt,
            output_model=ReportAnalysisContent,
            max_tokens=MAX_OUTPUT_TOKENS,
            effort=EFFORT,
        )


def mark_submitted(receipt_no: str, batch_id: str) -> None:
    """대기 행에 배치 id 를 적는다. 제출이 끝난 뒤에만 부른다."""
    with get_session() as session:
        row = session.get(DartAnalysis, (receipt_no, MODEL, PROMPT_VERSION))
        if row is not None:
            row.batch_id = batch_id
            session.commit()


def pending_batch_ids() -> list[str]:
    """결과를 기다리는 배치 id 들."""
    with get_session() as session:
        return list(
            session.execute(
                select(DartAnalysis.batch_id)
                .where(DartAnalysis.status == STATUS_PENDING, DartAnalysis.batch_id != "")
                .distinct()
            ).scalars()
        )


def apply_outcome(outcome: analysis_batch.Outcome) -> bool:
    """배치 결과 한 건을 대기 행에 덮어쓴다. 우리 행이 아니면 False."""
    if not outcome.custom_id.startswith(CUSTOM_ID_PREFIX):
        return False
    receipt_no = outcome.custom_id[len(CUSTOM_ID_PREFIX) :]

    with get_session() as session:
        row = session.get(DartAnalysis, (receipt_no, MODEL, PROMPT_VERSION))
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
                content = analysis_batch.parse_content(outcome.text or "", ReportAnalysisContent)
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
                "사업보고서 배치 분석 완료: %s FY%d · 입력 %d · 출력 %d · 추정 $%.3f",
                row.corp_name,
            row.fiscal_year,
                row.input_tokens,
                row.output_tokens,
                row.cost_micro_usd / 1_000_000,
            )

        session.commit()
        return True
