"""배치 전선 규격 점검 스크립트.

**Anthropic API 를 실제로 부른다. 돈이 든다 — 다만 아주 조금.**

우리 테스트는 배치 응답을 가짜로 만들어 확인한다. 그것으로는 알 수 없는 것이 하나 있다:
**우리가 만든 요청을 서버가 받아 주는가.** `thinking` 과 `output_config.format` 을 배치
요청 본문에 함께 넣는 것이 동기 호출과 똑같이 동작하는지는 한 번 보내 봐야 안다.

그래서 여기서는 **진짜 스키마로, 아주 짧은 문서 하나만** 보낸다. 입력 몇백 토큰에
출력 상한 500 이라 반값을 적용하면 1원 남짓이다. 실제 10-K(입력 4만 토큰)와 견주면
백분의 일 수준이다.

확인하는 것 넷:

1. 요청이 400 으로 거절되지 않는가 (파라미터 조합이 맞는가)
2. 배치가 끝나는가
3. 결과가 우리 스키마대로 오는가 (`parse_content` 가 통과하는가)
4. 사용량이 우리가 세는 것과 같은 자리에 오는가

실행 (서버에서 — API 키가 거기 있다):
    cd /opt/stock && .venv/bin/python backend/scripts/check_batch.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# 이 파일 → scripts → backend. backend 를 경로에 넣어야 `app` 패키지를 찾는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import analysis_batch, llm_budget  # noqa: E402
from app.services.tenk_analysis import TenKAnalysisContent  # noqa: E402

# 진짜 10-K 대신 쓰는 장난감 문서. 다섯 필드를 채울 만큼만 있으면 된다.
TOY_DOCUMENT = """\
Item 1. Business
The Company designs and sells a single product: a mechanical pencil. Revenue comes
from retail sales and from a subscription that mails replacement leads every month.
The Company operates one segment: Writing Instruments.

Item 1A. Risk Factors
We depend on a single supplier for graphite. Loss of that supplier would interrupt
production. We also face the risks common to all public companies, including general
economic conditions and changes in law.

Item 7. Management's Discussion and Analysis
Management attributes the increase in revenue to growth in the subscription program
and to wider retail distribution. Management notes that costs rose because of higher
graphite prices.
"""

MAX_OUTPUT_TOKENS = 500
POLL_SECONDS = 10
GIVE_UP_AFTER = 15 * 60


async def main() -> int:
    request = analysis_batch.build_request(
        custom_id="check-1",
        model="claude-sonnet-5",
        system=(
            "당신은 미국 상장사의 연차보고서를 읽고 한국어로 정리하는 애널리스트입니다. "
            "어떤 수치도 쓰지 마십시오."
        ),
        prompt=TOY_DOCUMENT,
        output_model=TenKAnalysisContent,
        max_tokens=MAX_OUTPUT_TOKENS,
        effort="high",
    )

    client = analysis_batch.new_client()
    try:
        print("1) 요청을 보냅니다…")
        batch_id = await analysis_batch.submit(client, [request])
        print(f"   받아들여졌습니다: {batch_id}")

        print("2) 끝나기를 기다립니다 (보통 1분 안)…")
        started = time.monotonic()
        while True:
            outcomes = await analysis_batch.collect(client, batch_id)
            if outcomes is not None:
                break
            waited = int(time.monotonic() - started)
            if waited > GIVE_UP_AFTER:
                print(f"   {waited}초가 지나도 안 끝납니다. 나중에 다시 확인하세요: {batch_id}")
                return 1
            print(f"   아직 처리 중… ({waited}초)")
            await asyncio.sleep(POLL_SECONDS)

        outcome = outcomes[0]
        print(f"   끝났습니다. 입력 {outcome.input_tokens} · 출력 {outcome.output_tokens}")

        if not outcome.ok:
            print(f"3) 실패: {outcome.error}")
            return 1

        print("3) 스키마로 검증합니다…")
        content = analysis_batch.parse_content(outcome.text or "", TenKAnalysisContent)
        print(f"   사업 요약: {content.business_summary[:60]}…")
        print(f"   위험요인 {len(content.key_risks)}건 · 부문 {len(content.segments)}개")

        cost = llm_budget.cost_micro_usd(
            outcome.input_tokens, outcome.output_tokens, batch=True
        )
        full = llm_budget.cost_micro_usd(outcome.input_tokens, outcome.output_tokens)
        print(f"4) 비용: ${cost / 1_000_000:.5f} (정가라면 ${full / 1_000_000:.5f})")
        print("\n전선 규격 정상. 자동 분석을 배치로 돌려도 됩니다.")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
