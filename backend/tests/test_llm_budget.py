"""LLM 비용 계산 테스트.

돈과 직접 닿는 코드라 값이 어긋나면 조용히 틀린다 — 화면에 표시되는 숫자가 실제 청구와
달라도 즉시 알아채기 어렵다. 그래서 계산 자체를 못 박는다.

달러를 float 대신 **100만분의 1달러 단위 정수**로 다루는 이유가 여기 있다. float 로 두면
건별로는 오차가 안 보이지만 누적 합계가 어긋난다.
"""

from __future__ import annotations

from app.services.llm_budget import (
    PRICE_INPUT_PER_MTOK_USD,
    PRICE_OUTPUT_PER_MTOK_USD,
    cost_micro_usd,
)


def test_price_constants_are_list_price():
    """정가 기준이다. 도입가 기간에는 실제 청구가 이보다 적다 —
    적게 추정하는 쪽이 위험하므로 일부러 비싼 쪽으로 잡았다."""
    assert PRICE_INPUT_PER_MTOK_USD == 3.0
    assert PRICE_OUTPUT_PER_MTOK_USD == 15.0


def test_zero_tokens_costs_nothing():
    assert cost_micro_usd(0, 0) == 0


def test_one_million_input_tokens():
    """입력 100만 토큰 = $3.00 = 3,000,000 마이크로달러."""
    assert cost_micro_usd(1_000_000, 0) == 3_000_000


def test_one_million_output_tokens():
    assert cost_micro_usd(0, 1_000_000) == 15_000_000


def test_realistic_analysis_cost():
    """실측값으로 확인 — 삼성전자 사업보고서 1건(입력 54,694 / 출력 5,067)."""
    micro = cost_micro_usd(54_694, 5_067)
    # $0.164 + $0.076 = $0.240
    assert micro == 240_087
    assert round(micro / 1_000_000, 3) == 0.240


def test_returns_integer_not_float():
    """정수여야 SQLite 에 넣고 SUM 해도 누적 오차가 없다."""
    value = cost_micro_usd(32_052, 2_645)
    assert isinstance(value, int)


def test_accumulation_has_no_drift():
    """같은 건을 1,000번 더해도 오차가 없다. float 이면 여기서 어긋난다."""
    one = cost_micro_usd(54_694, 5_067)
    assert one * 1_000 == sum(cost_micro_usd(54_694, 5_067) for _ in range(1_000))
