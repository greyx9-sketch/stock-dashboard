"""분석을 배치로 맡기는 부분 — 국내·미국이 함께 쓴다.

## 왜 배치인가

같은 모델·같은 프롬프트인데 **모든 토큰이 반값**이다(입력·출력·캐시 전부). 대신 결과가
즉시 오지 않고 **최대 24시간** 안에 온다(대개 한 시간 안). CLAUDE.md 가 이미
"배치 작업은 Batch API(50% 할인)를 쓴다"고 정해 뒀는데 지켜지지 않고 있었다.

## 어디에 쓰고 어디에 안 쓰는가

**밤에 도는 자동 분석에만 쓴다**(`auto_analysis.py`). 아무도 기다리지 않는 일이라
24시간 창을 쓸 수 있다.

**사람이 "분석하기"를 누른 경우에는 쓰지 않는다.** 화면 앞에서 기다리는 사람에게
"내일쯤 나옵니다"는 답이 될 수 없다. 그 경로는 지금까지처럼 동기 호출이다.

## 스키마를 SDK 내부 함수 없이 만든다

동기 경로는 `client.messages.parse(output_format=PydanticModel)` 을 쓴다. SDK 가 그 안에서
Pydantic 스키마를 손봐 `output_config.format` 으로 보낸다. 배치에는 그 헬퍼가 없으므로
같은 모양을 우리가 만들어야 한다.

SDK 의 내부 함수(`anthropic.lib._parse._transform`)를 가져다 쓰면 짧지만, **밑줄로 시작하는
비공개 경로라 SDK 를 올리는 날 조용히 깨진다.** 그래서 여기서 직접 만들고,
`tests/test_analysis_batch.py` 가 **SDK 것과 글자 하나까지 같은지** 대조한다.
SDK 가 규칙을 바꾸면 배포가 아니라 테스트에서 걸린다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from pydantic import BaseModel, TypeAdapter

logger = logging.getLogger(__name__)


def new_client() -> anthropic.AsyncAnthropic:
    """배치용 클라이언트. 쓰는 쪽이 닫는다."""
    from app.config import get_settings

    return anthropic.AsyncAnthropic(api_key=get_settings().require("anthropic_api_key"))


# 반값 할인은 `llm_budget.BATCH_DISCOUNT` 에 한 군데만 둔다 — 가격이 두 곳에 있으면
# 한쪽만 고쳐도 비용 기록이 조용히 어긋난다.


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic 모델 → API 가 받는 JSON 스키마.

    Pydantic 이 만든 것에 **객체마다 `additionalProperties: false` 와 `required` 를 채워
    넣는 것**이 전부다. 그것이 SDK 가 하는 일과 같다는 것은 테스트가 지킨다.
    """
    return _tighten(TypeAdapter(model).json_schema())


def _tighten(node: Any) -> Any:
    if isinstance(node, dict):
        out = {key: _tighten(value) for key, value in node.items()}
        if out.get("type") == "object" and "properties" in out:
            # 모델에 없는 필드를 지어내지 못하게 하고, 모든 필드를 필수로 둔다.
            out.setdefault("additionalProperties", False)
            out.setdefault("required", list(out["properties"]))
        return out
    if isinstance(node, list):
        return [_tighten(item) for item in node]
    return node


def build_request(
    *,
    custom_id: str,
    model: str,
    system: str,
    prompt: str,
    output_model: type[BaseModel],
    max_tokens: int,
    effort: str,
) -> Request:
    """배치에 넣을 요청 한 건.

    동기 경로(`messages.parse`)와 **같은 인자를 보낸다.** 한쪽만 바뀌면 배치 결과와
    수동 결과가 달라지므로, 고칠 때는 두 곳을 같이 고쳐야 한다.
    """
    return Request(
        custom_id=custom_id,
        params=MessageCreateParamsNonStreaming(
            model=model,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": json_schema_for(output_model)},
            },
            messages=[{"role": "user", "content": prompt}],
        ),
    )


@dataclass(frozen=True)
class Outcome:
    """배치 요청 한 건의 결과."""

    custom_id: str
    #: 성공했을 때의 본문(JSON 문자열). 실패면 None.
    text: str | None
    input_tokens: int
    output_tokens: int
    #: 실패 이유. 성공이면 None. 화면에 그대로 보여줄 수 있게 한국어로 쓴다.
    error: str | None

    @property
    def ok(self) -> bool:
        return self.text is not None


async def submit(client: anthropic.AsyncAnthropic, requests: list[Request]) -> str:
    """배치를 맡기고 배치 id 를 돌려준다."""
    batch = await client.messages.batches.create(requests=requests)
    logger.info("배치 제출 — %s (%d건)", batch.id, len(requests))
    return batch.id


async def collect(
    client: anthropic.AsyncAnthropic, batch_id: str
) -> list[Outcome] | None:
    """끝났으면 결과 목록, 아직이면 None.

    **아직 안 끝난 것과 결과가 비어 있는 것을 구분한다.** 둘을 같은 값으로 돌려주면
    부르는 쪽이 "결과 없음"으로 오해해 대기 중인 행을 실패로 덮어쓴다.
    """
    batch = await client.messages.batches.retrieve(batch_id)
    if batch.processing_status != "ended":
        return None

    outcomes: list[Outcome] = []
    async for result in await client.messages.batches.results(batch_id):
        outcomes.append(_to_outcome(result))
    return outcomes


def _to_outcome(result: Any) -> Outcome:
    custom_id = result.custom_id
    kind = result.result.type

    if kind == "succeeded":
        message = result.result.message
        usage = message.usage
        if message.stop_reason == "refusal":
            return Outcome(
                custom_id,
                None,
                usage.input_tokens,
                usage.output_tokens,
                "안전 정책에 따라 이 문서의 분석이 거절되었습니다. 원문 링크로 확인해 주세요.",
            )
        text = next((b.text for b in message.content if b.type == "text"), None)
        if not text:
            return Outcome(
                custom_id,
                None,
                usage.input_tokens,
                usage.output_tokens,
                f"분석 결과가 비어 있습니다 (종료 사유: {message.stop_reason}).",
            )
        return Outcome(custom_id, text, usage.input_tokens, usage.output_tokens, None)

    # 실패는 토큰을 쓰지 않았거나 알 수 없다. 0 으로 둔다 — 하루 상한 계산에서
    # 부르지 않은 것으로 세어져 다음에 다시 시도된다.
    if kind == "errored":
        detail = getattr(result.result.error, "type", "unknown")
        return Outcome(custom_id, None, 0, 0, f"배치 처리 실패 ({detail})")
    if kind == "expired":
        return Outcome(custom_id, None, 0, 0, "배치가 24시간 안에 끝나지 않아 만료됐습니다.")
    return Outcome(custom_id, None, 0, 0, f"배치가 취소됐습니다 ({kind}).")


def parse_content(text: str, output_model: type[BaseModel]) -> BaseModel:
    """배치가 돌려준 JSON 문자열을 스키마로 검증한다.

    동기 경로에서는 SDK 가 해 주는 일이다. 배치에는 그 단계가 없어 여기서 한다.
    """
    return output_model.model_validate(json.loads(text))
