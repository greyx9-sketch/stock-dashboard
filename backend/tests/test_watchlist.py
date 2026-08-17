"""관심종목 — 순수 함수 테스트.

여기서 틀리면 **등락률이 하루 어긋난다.** 일봉의 [0] 을 기준가로 쓰면 "오늘 대비 오늘"
이 되어 항상 0% 가 되거나, 장 마감 후에 마지막 세션의 등락률이 사라진다. 그럴듯하게
보이는 종류의 실수라 눈으로는 잘 잡히지 않는다.

아래 캔들 모양은 2026-08-18 실제 응답에서 가져왔다(AAPL: 진행 중인 8/17 세션 + 직전
거래일 8/14, 삼성전자: 마감된 8/14 + 8/13).
"""

from __future__ import annotations

from decimal import Decimal

from app.services.price_poller import classify_market
from app.services.watchlist import normalize_symbol, pick_base


# ---------------------------------------------------------------- 코드 정규화


def test_us_ticker_is_uppercased():
    """`aapl` 과 `AAPL` 이 각각 담기면 같은 종목이 두 줄로 보인다."""
    assert normalize_symbol("aapl") == "AAPL"
    assert normalize_symbol("  ko  ") == "KO"


def test_kr_code_is_untouched():
    assert normalize_symbol("005930") == "005930"
    assert normalize_symbol(" 000660 ") == "000660"


def test_market_is_decided_by_shape():
    """국내는 숫자 6자리, 그 외는 미국이다. 목록이 두 시장을 섞어 담으므로 이 판정이 필요하다."""
    assert classify_market(normalize_symbol("005930")) == "KR"
    assert classify_market(normalize_symbol("aapl")) == "US"


# ---------------------------------------------------------------- 기준가 고르기


def test_base_is_the_second_candle_not_the_first():
    """장중 — [0] 은 진행 중인 봉이다. 그것을 기준가로 쓰면 등락률이 늘 0% 가 된다."""
    candles = [
        {"timestamp": "2026-08-17T00:00:00-04:00", "closePrice": "303.615"},
        {"timestamp": "2026-08-14T00:00:00-04:00", "closePrice": "305.93"},
        {"timestamp": "2026-08-13T00:00:00-04:00", "closePrice": "305.26"},
    ]
    assert pick_base(candles) == (Decimal("305.93"), "2026-08-14")


def test_base_after_close_is_the_previous_session():
    """마감 후 — [0] 이 마지막으로 끝난 세션이다. 기준가는 그 앞 세션이라야
    "마지막 세션의 등락률"이 보인다. 0% 로 눌러 버리면 정보가 사라진다."""
    candles = [
        {"timestamp": "2026-08-14T00:00:00+09:00", "closePrice": "274500"},
        {"timestamp": "2026-08-13T00:00:00+09:00", "closePrice": "263000"},
    ]
    assert pick_base(candles) == (Decimal("263000"), "2026-08-13")


def test_base_is_none_when_history_is_too_short():
    """신규 상장 종목은 봉이 하나뿐일 수 있다. 등락률 자리만 비우고 목록에는 남긴다."""
    assert pick_base([]) is None
    assert pick_base([{"timestamp": "2026-08-17T00:00:00-04:00", "closePrice": "1"}]) is None


def test_base_is_none_when_close_is_garbage():
    candles = [
        {"timestamp": "2026-08-17", "closePrice": "1"},
        {"timestamp": "2026-08-14", "closePrice": None},
    ]
    assert pick_base(candles) is None


def test_base_keeps_decimal_precision():
    """미국 주가는 소수점이 있다. float 로 받으면 87.71 이 87.70999... 가 된다."""
    candles = [
        {"timestamp": "2026-08-17", "closePrice": "87.09"},
        {"timestamp": "2026-08-14", "closePrice": "87.71"},
    ]
    base, _ = pick_base(candles)  # type: ignore[misc]
    assert base == Decimal("87.71")
    assert str(base) == "87.71"
