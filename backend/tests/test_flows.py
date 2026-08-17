"""수급 파싱 테스트.

여기서 가장 위험한 것은 **비율 단위**다. 토스는 공매도 비중·신용 잔고율을 `0.0588`
처럼 소수로 준다. 100을 곱하는 것을 놓치면 "공매도 비중 0.06%" 가 되는데, 그럴듯해
보이는 숫자라 한참 모른 채 지나갈 수 있다.

두 번째는 **한쪽만 비어 있는 응답**이다. 프로그램매매는 차익·비차익 둘 중 하나만
오는 날이 있다. 없는 쪽을 0으로 읽어 합계를 내는 것은 맞지만(그 종목에 차익거래가
없었다는 뜻), 둘 다 없으면 합계 0이 아니라 "자료 없음"이어야 한다.

아래 자료 모양은 2026-08 삼성전자(005930) 실제 응답에서 가져왔다.
"""

from __future__ import annotations

from app.services.flows import (
    Flows,
    parse_credit,
    parse_investors,
    parse_lending,
    parse_program,
    parse_short_selling,
)


# ---------------------------------------------------------------- 투자자별


def test_investors_keeps_newest_first_order():
    """토스가 최신순으로 준다. 화면도 그 순서로 읽으므로 다시 정렬하지 않는다."""
    days = parse_investors(
        [
            {"date": "2026-08-14", "individual": {"netBuyVolume": "-3645737"}},
            {"date": "2026-08-13", "individual": {"netBuyVolume": "-5164773"}},
        ]
    )
    assert [d.date for d in days] == ["2026-08-14", "2026-08-13"]


def test_investors_reads_three_groups():
    days = parse_investors(
        [
            {
                "date": "2026-08-14",
                "individual": {"netBuyVolume": "-3645737"},
                "foreigner": {"netBuyVolume": "5722346"},
                "institution": {"netBuyVolume": "-2081252"},
            }
        ]
    )
    assert (days[0].individual, days[0].foreigner, days[0].institution) == (
        -3645737,
        5722346,
        -2081252,
    )


def test_investors_missing_group_is_none_not_zero():
    """0(순매수 없음)과 자료 없음은 다르다. 화면에서 0 과 — 로 구분해 보여준다."""
    days = parse_investors([{"date": "2026-08-14", "individual": {}}])
    assert days[0].individual is None
    assert days[0].foreigner is None


def test_investors_skips_rows_without_date():
    """날짜가 없으면 표에 놓을 자리가 없다. 그 행만 버린다."""
    days = parse_investors(
        [
            {"individual": {"netBuyVolume": "100"}},
            {"date": "", "individual": {"netBuyVolume": "100"}},
            {"date": "2026-08-14", "individual": {"netBuyVolume": "100"}},
        ]
    )
    assert [d.date for d in days] == ["2026-08-14"]


def test_investors_handles_empty_records():
    assert parse_investors([]) == []


# ---------------------------------------------------------------- 비율 지표


def test_short_selling_converts_ratio_to_percent():
    """실측 — 0.0588 은 5.88% 다. 0.06% 가 아니다."""
    metric = parse_short_selling(
        [{"date": "2026-08-14", "shortSellingVolumeRate": "0.0588"}]
    )
    assert metric is not None
    assert metric.value == "5.88"
    assert metric.unit == "%"
    assert metric.as_of == "2026-08-14"


def test_credit_reads_nested_margin_loan():
    """신용 잔고율은 `marginLoan` 안에 들어 있다. 한 겹을 빼먹으면 조용히 None 이 된다."""
    metric = parse_credit(
        [{"date": "2026-08-14", "marginLoan": {"balanceRate": "0.0039"}}]
    )
    assert metric is not None
    assert metric.value == "0.39"


def test_credit_returns_none_when_margin_loan_missing():
    assert parse_credit([{"date": "2026-08-14"}]) is None


def test_rate_metrics_skip_to_first_usable_row():
    """갱신 시각 차이로 최신 행이 비어 있을 수 있다. 비면 다음 행으로 내려간다."""
    metric = parse_short_selling(
        [
            {"date": "2026-08-17", "shortSellingVolumeRate": None},
            {"date": "2026-08-14", "shortSellingVolumeRate": "0.0588"},
        ]
    )
    assert metric is not None
    # 기준일도 함께 내려와야 한다. 값은 14일치인데 날짜만 17일로 남으면 거짓 표기가 된다.
    assert metric.as_of == "2026-08-14"


# ---------------------------------------------------------------- 수량 지표


def test_lending_formats_with_separator():
    metric = parse_lending([{"date": "2026-08-14", "balanceQuantity": "84200755"}])
    assert metric is not None
    assert metric.value == "84,200,755"
    assert metric.unit == "주"


def test_program_sums_arbitrage_and_non_arbitrage():
    metric = parse_program(
        [
            {
                "date": "2026-08-14",
                "arbitrage": {"netBuyVolume": "-51190"},
                "nonArbitrage": {"netBuyVolume": "-100000"},
            }
        ]
    )
    assert metric is not None
    assert metric.value == "-151,190"


def test_program_treats_one_missing_side_as_zero():
    """차익거래가 없던 날이다. 비차익만으로 합계를 낸다."""
    metric = parse_program(
        [{"date": "2026-08-14", "nonArbitrage": {"netBuyVolume": "12345"}}]
    )
    assert metric is not None
    assert metric.value == "+12,345"


def test_program_returns_none_when_both_sides_missing():
    """둘 다 없으면 "합계 0" 이 아니라 자료 없음이다."""
    assert parse_program([{"date": "2026-08-14", "arbitrage": {}}]) is None


def test_program_always_shows_sign():
    """순매수는 방향이 핵심이라 양수에도 부호를 붙인다."""
    metric = parse_program([{"date": "2026-08-14", "arbitrage": {"netBuyVolume": "7"}}])
    assert metric is not None
    assert metric.value.startswith("+")


def test_quantity_metrics_handle_empty_records():
    assert parse_lending([]) is None
    assert parse_program([]) is None


# ---------------------------------------------------------------- 부분 실패 판정


def test_is_empty_only_when_nothing_arrived():
    """지표 하나라도 왔으면 화면에 내보낸다. 전부 비었을 때만 오류로 다룬다."""
    assert Flows(symbol="005930").is_empty

    lending = parse_lending([{"date": "2026-08-14", "balanceQuantity": "1"}])
    assert lending is not None
    assert not Flows(symbol="005930", metrics=[lending]).is_empty

    days = parse_investors([{"date": "2026-08-14", "individual": {"netBuyVolume": "1"}}])
    assert not Flows(symbol="005930", investors=days).is_empty
