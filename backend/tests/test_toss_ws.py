"""웹소켓 체결 피드 회귀 테스트.

**네트워크를 쓰지 않는다.** 서버가 보내는 프레임을 그대로 흉내 내어, 우리가 그것을
어떻게 해석하는지만 확인한다. 실제 연결은 사람이 한 번 확인했다(2026-08-24, 미국
프리마켓 30초에 63건 수신).

여기서 지키는 것 셋:

1. **거부당한 종목을 다시 넣지 않는다.** 원문이 못 박은 규칙이다 — 원인을 고치기
   전에는 다시 선언해도 같은 이유로 또 거부된다. 계속 넣으면 재연결할 때마다 같은
   거부가 반복된다.
2. **구독 한도(100건)를 넘기지 않는다.** 넘기면 `too-many-topics` 로 선언 **전체**가
   거부되어, 한 종목 때문에 모든 종목이 실시간을 잃는다.
3. **아무도 안 보는 종목의 체결은 버린다.** 구독 해제가 반영되기까지 프레임이 계속
   오는데, 받아 두면 이미 지운 종목이 캐시에 되살아난다.
"""

from __future__ import annotations

import json
from decimal import Decimal

from app.clients.toss_ws import MAX_TOPICS, TossTradeFeed, _share_quota


def _feed(seen: list | None = None) -> TossTradeFeed:
    store = seen if seen is not None else []
    return TossTradeFeed(lambda s, p, t: store.append((s, p, t)))


# ---------------------------------------------------------------- 체결 프레임 해석


def test_trade_frame_is_read_as_price():
    """원문 예시 그대로의 프레임을 넣어 본다."""
    seen: list = []
    feed = _feed(seen)
    feed._handle(
        json.dumps(
            {
                "type": "message",
                "topic": "trade:us:AAPL",
                "data": {
                    "price": "243.26",
                    "volume": "8",
                    "timestamp": "2026-06-18T23:30:00.000+09:00",
                    "currency": "USD",
                },
            }
        )
    )
    assert seen == [("AAPL", Decimal("243.26"), "2026-06-18T23:30:00.000+09:00")]


def test_korean_symbol_survives_the_topic_split():
    """국내는 6자리 숫자다. topic 을 쪼갤 때 앞의 `trade:kr:` 만 떼야 한다."""
    seen: list = []
    _feed(seen)._handle(
        json.dumps({"type": "message", "topic": "trade:kr:005930", "data": {"price": "72000"}})
    )
    assert seen[0][0] == "005930"


def test_broken_frames_are_ignored():
    """깨진 프레임 하나에 연결이 죽으면 안 된다. 조용히 넘긴다."""
    seen: list = []
    feed = _feed(seen)
    for raw in [
        "PONG",  # JSON 이 아니다
        json.dumps([1, 2, 3]),  # 객체가 아니다
        json.dumps({"type": "message", "topic": "이상함", "data": {"price": "1"}}),
        json.dumps({"type": "message", "topic": "trade:us:AAPL", "data": {}}),  # 가격 없음
        json.dumps({"type": "message", "topic": "trade:us:AAPL", "data": {"price": "-"}}),
    ]:
        feed._handle(raw)
    assert seen == []


def test_pong_is_harmless():
    seen: list = []
    feed = _feed(seen)
    feed._handle(json.dumps({"type": "pong"}))
    assert seen == []


# ---------------------------------------------------------------- 구독 ack


def test_subscribed_symbols_are_tracked():
    feed = _feed()
    feed._handle(
        json.dumps(
            {
                "type": "subscriptions",
                "subscribed": ["trade:us:AAPL", "trade:kr:005930"],
                "rejected": [],
            }
        )
    )
    assert feed.subscribed == {"AAPL", "005930"}


def test_rejected_symbol_is_never_declared_again():
    """**회귀 방지.** 거부된 종목을 다시 넣으면 재연결할 때마다 같은 거부가 반복된다."""
    feed = _feed()
    feed.set_symbols(["005930", "999999"], [])
    feed._handle(
        json.dumps(
            {
                "type": "subscriptions",
                "subscribed": ["trade:kr:005930"],
                "rejected": [
                    {
                        "target": "trade:kr:999999",
                        "code": "stock-not-found",
                        "message": "해당 종목을 찾을 수 없습니다.",
                    }
                ],
            }
        )
    )
    # 다시 넣으려 해도 선언에서 빠진다.
    feed.set_symbols(["005930", "999999"], [])
    codes = [c for item in feed._declaration() for c in item["codes"]]
    assert "999999" not in codes
    assert "005930" in codes


def test_market_mismatch_is_also_permanent():
    """시장이 안 맞는 종목도 고치기 전에는 계속 거부된다."""
    feed = _feed()
    feed.set_symbols([], ["005930"])
    feed._handle(
        json.dumps(
            {
                "type": "subscriptions",
                "subscribed": [],
                "rejected": [
                    {"target": "trade:us:005930", "code": "symbol-market-mismatch", "message": "x"}
                ],
            }
        )
    )
    feed.set_symbols([], ["005930", "AAPL"])
    codes = [c for item in feed._declaration() for c in item["codes"]]
    assert codes == ["AAPL"]


# ---------------------------------------------------------------- 구독 한도


def test_declaration_never_exceeds_the_limit():
    """한도를 넘기면 `too-many-topics` 로 **선언 전체**가 거부된다.

    한 종목이 많아졌다고 모든 종목이 실시간을 잃으면 안 된다.
    """
    feed = _feed()
    feed.set_symbols([f"{i:06d}" for i in range(90)], [f"US{i}" for i in range(90)])
    codes = [c for item in feed._declaration() for c in item["codes"]]
    assert len(codes) <= MAX_TOPICS


def test_one_market_can_use_the_whole_quota():
    """국내만 보고 있는데 미국 몫 50자리를 비워 두면 그냥 손해다."""
    kr, us = _share_quota([f"{i:06d}" for i in range(100)], [], MAX_TOPICS)
    assert len(kr) == MAX_TOPICS
    assert us == []


def test_both_markets_share_when_both_are_crowded():
    kr, us = _share_quota([f"{i:06d}" for i in range(80)], [f"US{i}" for i in range(80)], 100)
    assert len(kr) + len(us) == 100
    # 한쪽이 통째로 먹지 않는다.
    assert len(kr) >= 40 and len(us) >= 40


def test_small_lists_are_left_alone():
    kr, us = _share_quota(["005930"], ["AAPL"], 100)
    assert kr == ["005930"] and us == ["AAPL"]


# ---------------------------------------------------------------- 덮고 있는가


def test_covers_is_false_while_disconnected():
    """연결이 없으면 아무것도 못 덮는다. 폴러가 빠른 주기로 돌아가야 한다."""
    feed = _feed()
    feed._connected = False
    feed._subscribed = {"trade:us:AAPL"}
    assert feed.covers(["AAPL"]) is False


def test_covers_needs_every_symbol():
    """하나라도 빠지면 거짓이다 — 그 하나가 화면에서 멈춰 보이면 안 된다."""
    feed = _feed()
    feed._connected = True
    feed._subscribed = {"trade:us:AAPL"}
    assert feed.covers(["AAPL"]) is True
    assert feed.covers(["AAPL", "TSLA"]) is False


def test_covers_nothing_is_true():
    """받을 것이 없으면 빠뜨린 것도 없다."""
    feed = _feed()
    feed._connected = False
    assert feed.covers([]) is True


# ---------------------------------------------------------------- 선언 만들기


def test_empty_market_is_not_declared():
    """빈 codes 로 선언하면 `no-codes` 로 거부된다."""
    feed = _feed()
    feed.set_symbols(["005930"], [])
    decl = feed._declaration()
    assert len(decl) == 1
    assert decl[0]["type"] == "trade:kr"


def test_declaring_nothing_is_an_empty_array():
    """빈 배열은 '전체 해제'다. 아무도 안 볼 때 구독을 놓아야 한다."""
    assert _feed()._declaration() == []


def test_same_symbols_do_not_trigger_a_redeclare():
    """화면이 같은 목록을 계속 보내온다. 그때마다 선언하면 5회/초 한도에 걸린다."""
    feed = _feed()
    feed.set_symbols(["005930"], ["AAPL"])
    feed._dirty.clear()
    feed.set_symbols(["005930"], ["AAPL"])
    assert not feed._dirty.is_set()


def test_changed_symbols_do_trigger_a_redeclare():
    feed = _feed()
    feed.set_symbols(["005930"], [])
    feed._dirty.clear()
    feed.set_symbols(["005930", "000660"], [])
    assert feed._dirty.is_set()


# ================================================================== 폴러와 붙였을 때
#
# 웹소켓과 폴링이 같은 캐시를 공유한다. 그 경계에서 어긋나기 쉬운 것들을 못 박는다.

from datetime import datetime, timezone  # noqa: E402

from app.services.price_poller import (  # noqa: E402
    WS_SAFETY_INTERVAL_SEC,
    MarketState,
    PricePoller,
)


def _poller_watching(*symbols: str) -> PricePoller:
    p = PricePoller()
    p.register(list(symbols))
    return p


def test_trade_updates_the_same_cache_polling_uses():
    """웹소켓으로 받은 값도 폴링이 쓰는 캐시에 그대로 들어가야 화면에 보인다."""
    p = _poller_watching("AAPL")
    p._on_trade("AAPL", Decimal("243.26"), "2026-06-18T23:30:00.000+09:00")

    cached = p.snapshot(["AAPL"])["AAPL"]
    assert cached.last_price == Decimal("243.26")
    assert cached.timestamp == "2026-06-18T23:30:00.000+09:00"


def test_trade_counts_as_a_successful_update():
    """가동 점검이 이 값으로 '현재가가 살아 있는가'를 본다.

    웹소켓만으로 값이 들어오는 동안 이걸 안 찍으면, 멀쩡한데 '갱신이 없다'고 운다.
    """
    p = _poller_watching("AAPL")
    assert p.last_success_at is None
    p._on_trade("AAPL", Decimal("243.26"), None)
    assert isinstance(p.last_success_at, datetime)
    assert p.last_success_at.tzinfo is timezone.utc


def test_trade_for_an_unwatched_symbol_is_dropped():
    """**회귀 방지.** 구독 해제가 반영되기까지 프레임이 계속 온다.

    그걸 받아 두면 아무도 안 보는 종목이 캐시에 되살아나고, 그 캐시는 지워지지 않는다.
    """
    p = _poller_watching("AAPL")
    p._on_trade("TSLA", Decimal("1"), None)
    assert p.snapshot(["TSLA"]) == {}


def _live(p: PricePoller, country: str = "US") -> None:
    p._markets[country] = MarketState("REGULAR", "정규장", "2026-08-24", None, None)


def test_rest_slows_down_when_the_socket_covers_everything():
    """값이 푸시로 들어오는 동안 REST 는 안전망이면 된다."""
    p = _poller_watching("AAPL")
    _live(p)
    p._feed._connected = True
    p._feed._subscribed = {"trade:us:AAPL"}

    assert p._next_delay({"KR": [], "US": ["AAPL"]}) == WS_SAFETY_INTERVAL_SEC


def test_rest_stays_fast_when_one_symbol_is_missing():
    """하나라도 웹소켓에서 빠지면 그 종목이 멈춰 보인다. 원래 주기로 돌아간다."""
    p = _poller_watching("AAPL", "TSLA")
    _live(p)
    p._feed._connected = True
    p._feed._subscribed = {"trade:us:AAPL"}  # TSLA 가 빠졌다

    assert p._next_delay({"KR": [], "US": ["AAPL", "TSLA"]}) == 1.0


def test_rest_stays_fast_when_the_socket_is_down():
    """웹소켓이 끊기면 폴링이 그대로 맡는다. 이게 사이트가 안 죽는 이유다."""
    p = _poller_watching("AAPL")
    _live(p)
    p._feed._connected = False

    assert p._next_delay({"KR": [], "US": ["AAPL"]}) == 1.0


def test_closed_market_is_not_sped_up_by_the_socket():
    """장이 닫혀 있으면 어차피 값이 안 바뀐다. 웹소켓이 붙었다고 더 자주 부르지 않는다."""
    p = _poller_watching("AAPL")
    p._markets["US"] = MarketState("CLOSED", "장 마감", "2026-08-24", None, None)
    p._feed._connected = True
    p._feed._subscribed = {"trade:us:AAPL"}

    assert p._next_delay({"KR": [], "US": ["AAPL"]}) == 60.0


def test_realtime_is_judged_per_request_not_globally():
    """**회귀 방지.** 국내 탭을 보다 미국 탭으로 옮기면, 국내 종목이 120초 동안
    목록에 남는다. 그 때문에 미국 화면이 "실시간 아님"으로 뜨던 것을 고쳤다.
    """
    p = _poller_watching("AAPL", "005930")
    p._feed._connected = True
    p._feed._subscribed = {"trade:us:AAPL"}  # 국내는 아직 안 붙었다

    assert p.realtime_for(["AAPL"]) is True       # 이 화면은 실시간이 맞다
    assert p.realtime_for(["AAPL", "005930"]) is False


def test_realtime_detail_says_polling_when_disconnected():
    """사람이 읽는 문장이다. '연결 끊김'이 보이되 고장처럼 읽히면 안 된다."""
    p = _poller_watching("AAPL")
    p._feed._connected = False
    assert "폴링" in p.realtime_detail


def test_realtime_detail_reports_partial_coverage():
    """100건 한도에 걸려 일부만 실시간일 수 있다. 그 사실을 숨기지 않는다."""
    p = _poller_watching("AAPL", "TSLA")
    p._feed._connected = True
    p._feed._subscribed = {"trade:us:AAPL"}
    assert "1/2" in p.realtime_detail
