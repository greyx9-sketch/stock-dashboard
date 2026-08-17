"""매크로 스트립 계산·파싱 테스트.

여기 실수가 나면 **틀린 숫자가 화면 맨 위에 뜬다.** 특히 비율 단위가 위험하다 —
매크로 피드는 기준금리를 `0.0275` 처럼 소수로 주는데, 100을 곱하는 것을 놓치면
"한국 기준금리 0.03%" 가 된다. 그럴듯해 보여서 한참 모른 채 지나갈 수 있다.
"""

from __future__ import annotations

from decimal import Decimal

from app.clients.macro_feed import FeedSeries, _parse
from app.services.macro import ORDER, _fmt, _num, _rate


# ---------------------------------------------------------------- 숫자 다루기


def test_num_parses_string_prices():
    """토스는 가격을 문자열로 준다. Decimal 로 받아 소수 오차를 피한다."""
    assert _num("6977.94") == Decimal("6977.94")
    assert _num("1419.1") == Decimal("1419.1")


def test_num_returns_none_for_garbage():
    for bad in (None, "", "-", "N/A", {}, []):
        assert _num(bad) is None


def test_fmt_adds_thousands_separator():
    assert _fmt(Decimal("6977.94"), 2) == "6,977.94"
    assert _fmt(Decimal("1419.1"), 1) == "1,419.1"
    assert _fmt(Decimal("84.77"), 2) == "84.77"


def test_rate_has_explicit_sign():
    """등락률은 부호가 붙어야 한다. 화면에서 색만으로 구분하면 흑백 인쇄나
    색약 사용자에게 정보가 사라진다."""
    assert _rate(Decimal("102"), Decimal("100")) == "+2.00"
    assert _rate(Decimal("98"), Decimal("100")) == "-2.00"
    assert _rate(Decimal("100"), Decimal("100")) == "+0.00"


def test_rate_matches_real_observed_value():
    """실측 — 코스피 6,977.94 / 전일 6,813.34 → +2.42%."""
    assert _rate(Decimal("6977.94"), Decimal("6813.34")) == "+2.42"


def test_rate_guards_zero_division():
    """기준가가 0 인 응답이 올 수 있다. 500 을 내지 않고 등락률만 비운다."""
    assert _rate(Decimal("100"), Decimal("0")) is None


# ---------------------------------------------------------------- 피드 파싱


def test_ratio_unit_is_flagged():
    """`ratio` 는 소수로 온다. 화면에 쓸 때 100을 곱해야 한다."""
    series = FeedSeries(
        id="bok_base_rate", name="한국 기준금리", unit="ratio",
        value=0.0275, ref_date="2026-07-16",
    )
    assert series.is_ratio is True
    assert round(series.value * 100, 2) == 2.75


def test_non_ratio_units_are_not_scaled():
    for unit in ("pp", "bp", "index", "percent"):
        series = FeedSeries(id="x", name="x", unit=unit, value=0.51, ref_date="2026-08-14")
        assert series.is_ratio is False


def test_parse_reads_latest_actual():
    row = {
        "id": "bok_base_rate",
        "name": "한국 기준금리",
        "unit": "ratio",
        "note": "정책금리",
        "latest": {"refDate": "2026-07-16", "actual": 0.0275},
    }
    parsed = _parse(row)
    assert parsed is not None
    assert parsed.id == "bok_base_rate"
    assert parsed.value == 0.0275
    assert parsed.ref_date == "2026-07-16"


def test_parse_skips_series_without_value():
    """값이 아직 없는 지표가 있다. 건너뛰되 전체를 실패시키지 않는다."""
    assert _parse({"id": "x", "latest": {}}) is None
    assert _parse({"id": "x", "latest": {"actual": None}}) is None
    assert _parse({"id": "x"}) is None


def test_parse_skips_row_without_id():
    assert _parse({"name": "이름만", "latest": {"actual": 1.0}}) is None


def test_parse_accepts_integer_value():
    """정수로 오는 지표도 있다(고용 건수 등)."""
    parsed = _parse({"id": "nfp", "unit": "count", "latest": {"actual": 150000}})
    assert parsed is not None
    assert parsed.value == 150000.0


# ---------------------------------------------------------------- 표시 순서


def test_display_order_is_kr_us_fx_policy_commodity():
    """국내 → 미국 → 환율 → 정책금리 → 원자재. 화면에서 읽는 흐름이다."""
    assert ORDER == [
        "kospi", "kosdaq", "sp500_proxy", "usdkrw", "policy_kr", "policy_us", "wti"
    ]


def test_display_order_has_no_duplicates():
    assert len(ORDER) == len(set(ORDER))
