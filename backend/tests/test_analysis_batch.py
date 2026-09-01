"""분석 배치 회귀 테스트.

자동 분석은 2026-09-01 부터 Batch API 로 맡긴다 — **모든 토큰이 반값**이고 결과는 최대
24시간 안에 온다. 값은 싸졌지만 갈 곳이 늘었으므로 여기서 못 박는 것도 늘었다.

이 파일이 지키는 것 넷:

1. **스키마가 SDK 와 같다.** 동기 경로는 `messages.parse(output_format=...)` 로 SDK 가
   스키마를 만들고, 배치 경로는 우리가 만든다. 둘이 어긋나면 **같은 문서인데 배치로
   돌렸을 때만 형식이 깨진다** — 밤에 조용히 일어나고 아침에 원인을 알 수 없다.
2. **배치와 동기가 같은 인자를 보낸다.** 모델·effort·thinking 이 갈리면 결과가 달라진다.
3. **대기 행을 두 번 맡기지 않는다.** 맡긴 순간 돈이 확정되므로 중복은 곧 두 배 지출이다.
4. **반값이 실제로 기록된다.** 여기가 틀리면 누적 비용이 두 배로 보인다.

**모델을 실제로 부르지 않는다.** 배치 제출·수거는 전부 가짜 응답으로 확인한다.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.models.base import get_session, init_db
from app.models.us_analysis import STATUS_FAILED, STATUS_OK, STATUS_PENDING, SecAnalysis
from app.services import analysis_batch, dart_analysis, llm_budget, tenk_analysis


# ---------------------------------------------------------------- 스키마


@pytest.mark.parametrize(
    "model",
    [tenk_analysis.TenKAnalysisContent, dart_analysis.ReportAnalysisContent],
    ids=["us", "kr"],
)
def test_schema_matches_the_sdk(model):
    """**이 파일에서 가장 중요한 테스트.**

    SDK 가 `messages.parse` 안에서 만드는 스키마와 우리가 배치용으로 만드는 스키마가
    글자 하나까지 같아야 한다. SDK 가 규칙을 바꾸면 배포가 아니라 여기서 걸린다.

    비공개 경로(`anthropic.lib._parse._transform`)를 **테스트에서만** 가져온다.
    제품 코드가 그것에 의존하면 SDK 를 올리는 날 서버가 안 뜬다.
    """
    from anthropic.lib._parse._transform import transform_schema
    from pydantic import TypeAdapter

    sdk = transform_schema(TypeAdapter(model).json_schema())
    ours = analysis_batch.json_schema_for(model)

    assert json.dumps(ours, sort_keys=True) == json.dumps(sdk, sort_keys=True)


def test_schema_forbids_invented_fields():
    """모델에 없는 필드를 지어내지 못하게 한다. 수치 필드가 끼어드는 것을 막는 울타리이기도 하다."""
    schema = analysis_batch.json_schema_for(tenk_analysis.TenKAnalysisContent)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["RiskItem"]["additionalProperties"] is False


# ---------------------------------------------------------------- 요청 모양


def test_batch_request_matches_the_sync_call():
    """배치와 동기가 같은 모델·같은 effort 로 간다. 갈리면 결과를 견줄 수 없다."""
    request = analysis_batch.build_request(
        custom_id="us:X",
        model=tenk_analysis.MODEL,
        system=tenk_analysis.SYSTEM_PROMPT,
        prompt="본문",
        output_model=tenk_analysis.TenKAnalysisContent,
        max_tokens=tenk_analysis.MAX_OUTPUT_TOKENS,
        effort=tenk_analysis.EFFORT,
    )
    params = request["params"]

    assert request["custom_id"] == "us:X"
    assert params["model"] == tenk_analysis.MODEL
    assert params["max_tokens"] == tenk_analysis.MAX_OUTPUT_TOKENS
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"]["effort"] == tenk_analysis.EFFORT
    assert params["output_config"]["format"]["type"] == "json_schema"


def test_custom_id_prefixes_do_not_collide():
    """국내·미국이 한 배치에 섞여 들어가므로 이름표가 겹치면 안 된다."""
    assert dart_analysis.CUSTOM_ID_PREFIX != tenk_analysis.CUSTOM_ID_PREFIX
    assert tenk_analysis.custom_id_for("0000320193-25-1").startswith("us:")
    assert dart_analysis.custom_id_for("20250311000123").startswith("kr:")


# ---------------------------------------------------------------- 결과 해석


def _succeeded(custom_id: str, text: str, *, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        custom_id=custom_id,
        result=SimpleNamespace(
            type="succeeded",
            message=SimpleNamespace(
                stop_reason=stop_reason,
                content=[SimpleNamespace(type="text", text=text)],
                usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
            ),
        ),
    )


def test_succeeded_result_carries_text_and_tokens():
    outcome = analysis_batch._to_outcome(_succeeded("us:A", '{"a":1}'))
    assert outcome.ok
    assert outcome.text == '{"a":1}'
    assert (outcome.input_tokens, outcome.output_tokens) == (1000, 200)


def test_refusal_is_a_failure_not_an_empty_success():
    """거절을 성공으로 두면 빈 분석이 저장되고 캐시가 영원히 껍데기를 돌려준다."""
    outcome = analysis_batch._to_outcome(
        _succeeded("us:A", "", stop_reason="refusal")
    )
    assert not outcome.ok
    assert "거절" in (outcome.error or "")


@pytest.mark.parametrize(
    "kind,expected",
    [("errored", "실패"), ("expired", "만료"), ("canceled", "취소")],
)
def test_failed_results_are_reported_in_korean(kind, expected):
    """화면에 그대로 보여줄 문구다. 영문 코드만 남기면 사용자가 읽을 수 없다."""
    result = SimpleNamespace(
        custom_id="us:A",
        result=SimpleNamespace(type=kind, error=SimpleNamespace(type="server_error")),
    )
    outcome = analysis_batch._to_outcome(result)
    assert not outcome.ok
    assert expected in (outcome.error or "")


# ---------------------------------------------------------------- 비용


def test_batch_costs_half():
    """반값이 실제로 기록되지 않으면 누적 비용이 두 배로 보인다."""
    full = llm_budget.cost_micro_usd(1_000_000, 100_000)
    half = llm_budget.cost_micro_usd(1_000_000, 100_000, batch=True)
    assert half == round(full * llm_budget.BATCH_DISCOUNT)
    assert half < full


# ---------------------------------------------------------------- 대기 행


@pytest.fixture
def _pending_row():
    init_db()
    with get_session() as session:
        session.query(SecAnalysis).delete()
        session.add(
            SecAnalysis(
                accession_no="0000320193-26-000001",
                model=tenk_analysis.MODEL,
                prompt_version=tenk_analysis.PROMPT_VERSION,
                cik="0000320193",
                ticker="AAPL",
                fiscal_year=2026,
                input_tokens=1234,
                status=STATUS_PENDING,
                batch_id="batch-1",
            )
        )
        session.commit()
    yield "0000320193-26-000001"


def _row(accession_no: str) -> SecAnalysis:
    with get_session() as session:
        return session.get(
            SecAnalysis,
            (accession_no, tenk_analysis.MODEL, tenk_analysis.PROMPT_VERSION),
        )


def test_pending_row_is_not_submitted_twice(_pending_row):
    """**맡긴 순간 돈이 확정된다.** 다시 맡기면 같은 문서를 두 번 사는 것이다."""
    row = _row(_pending_row)
    assert tenk_analysis._should_rerun(row, force=False) is False
    assert tenk_analysis._should_rerun(row, force=True) is False


def test_pending_row_counts_against_the_daily_limit(_pending_row):
    """제출한 건은 오늘 쓴 것으로 센다. 안 그러면 하루 상한을 넘겨 맡기게 된다."""
    assert llm_budget.calls_today() >= 1


def test_pending_batch_ids_are_listed(_pending_row):
    assert "batch-1" in tenk_analysis.pending_batch_ids()


def test_applying_a_good_result_fills_the_row(_pending_row):
    content = tenk_analysis.TenKAnalysisContent(
        business_summary="아이폰을 판다.",
        segments=["기기", "서비스"],
        key_risks=[
            tenk_analysis.RiskItem(
                title="공급망 집중",
                why_it_matters="한 지역에 생산이 몰려 있다.",
                is_boilerplate=False,
            )
        ],
        mdna_points=["서비스 매출이 늘었다고 설명"],
        moat_and_competition="생태계를 우위로 든다.",
    )
    outcome = analysis_batch.Outcome(
        custom_id=tenk_analysis.custom_id_for(_pending_row),
        text=content.model_dump_json(),
        input_tokens=1500,
        output_tokens=300,
        error=None,
    )

    assert tenk_analysis.apply_outcome(outcome) is True

    row = _row(_pending_row)
    assert row.status == STATUS_OK
    assert "아이폰" in row.content_json
    assert row.output_tokens == 300
    # 반값으로 기록됐는가.
    assert row.cost_micro_usd == llm_budget.cost_micro_usd(1500, 300, batch=True)


def test_applying_an_empty_result_marks_it_failed(_pending_row):
    """형식은 맞는데 알맹이가 빈 응답을 저장하면 캐시가 독이 된다."""
    empty = tenk_analysis.TenKAnalysisContent(
        business_summary="",
        segments=[],
        key_risks=[],
        mdna_points=[],
        moat_and_competition="",
    )
    outcome = analysis_batch.Outcome(
        custom_id=tenk_analysis.custom_id_for(_pending_row),
        text=empty.model_dump_json(),
        input_tokens=1500,
        output_tokens=10,
        error=None,
    )

    assert tenk_analysis.apply_outcome(outcome) is True
    assert _row(_pending_row).status == STATUS_FAILED


def test_applying_a_broken_result_marks_it_failed(_pending_row):
    """JSON 이 아니어도 서버가 죽지 않고 행에 이유가 남는다."""
    outcome = analysis_batch.Outcome(
        custom_id=tenk_analysis.custom_id_for(_pending_row),
        text="이건 JSON 이 아니다",
        input_tokens=1500,
        output_tokens=10,
        error=None,
    )

    assert tenk_analysis.apply_outcome(outcome) is True
    row = _row(_pending_row)
    assert row.status == STATUS_FAILED
    assert "형식" in row.error


def test_outcome_for_the_other_market_is_ignored(_pending_row):
    """한 배치에 국내·미국이 섞여 있다. 남의 결과를 자기 행에 쓰면 안 된다."""
    outcome = analysis_batch.Outcome(
        custom_id="kr:20250311000123", text="{}", input_tokens=1, output_tokens=1, error=None
    )
    assert tenk_analysis.apply_outcome(outcome) is False
    assert _row(_pending_row).status == STATUS_PENDING
