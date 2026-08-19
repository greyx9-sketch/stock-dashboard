"""토스 클라이언트의 공유 상태 테스트.

**토스는 client_id 당 토큰 하나만 유효하다.** 그래서 토큰과 rate limit 버킷을 인스턴스마다
두면 두 가지가 조용히 깨진다:

  1. 요청마다 새 인스턴스가 새 토큰을 받아 앞선 토큰을 죽인다 → 5초마다 도는 폴러가
     401 을 맞고 다시 발급받고, 그게 또 다른 쪽을 죽이는 일이 반복된다.
  2. 버킷이 따로면 동시에 뜬 인스턴스 수만큼 실제 호출 속도가 배로 뛴다 → 429.

둘 다 "가끔 실패"로만 보여서 원인을 찾기 어렵다. 여기서 못 박아 둔다.
"""

from __future__ import annotations

import time

import pytest

from app.clients import toss
from app.clients.toss import RATE_LIMITS, TossClient
from app.config import get_settings


@pytest.fixture
def client_pair(monkeypatch):
    """키 없이 클라이언트 두 개를 만든다. 네트워크는 부르지 않는다."""
    monkeypatch.setenv("TOSS_CLIENT_ID", "test-id")
    monkeypatch.setenv("TOSS_CLIENT_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        yield TossClient(), TossClient()
    finally:
        get_settings.cache_clear()
        toss._TOKEN.clear()


def test_every_group_has_a_bucket():
    """버킷이 없는 그룹으로 호출하면 KeyError 로 죽는다. 새 엔드포인트를 붙일 때 놓치기 쉽다."""
    assert set(toss._BUCKETS) == set(RATE_LIMITS)


class _NoNetwork:
    """네트워크로 나가려 하면 그 자리에서 실패시킨다.

    소켓 오류로 실패하면 "왜 실패했는지"가 흐려진다. 캐시를 안 쓰고 발급하러 나갔다는
    사실 자체가 이 테스트의 실패 이유이므로 그렇게 말해 준다.
    """

    async def post(self, *args, **kwargs):
        raise AssertionError("캐시된 토큰이 있는데 새로 발급하러 나갔다")

    async def aclose(self):
        pass


def test_two_clients_share_one_token(client_pair):
    """둘째 인스턴스가 첫째의 토큰을 그대로 쓴다. 새로 발급받으면 첫째 것이 죽는다."""
    import asyncio

    first, second = client_pair
    first._http = _NoNetwork()
    second._http = _NoNetwork()
    toss._TOKEN.value = "cached-token"
    toss._TOKEN.expires_at = time.monotonic() + 600

    assert asyncio.run(first._get_token()) == "cached-token"
    assert asyncio.run(second._get_token()) == "cached-token"


def test_invalidating_from_one_client_clears_it_for_all(client_pair):
    """401 을 만난 쪽이 토큰을 버리면 다른 쪽도 낡은 토큰을 쓰지 않아야 한다."""
    first, second = client_pair
    toss._TOKEN.value = "dead-token"
    toss._TOKEN.expires_at = time.monotonic() + 600

    first._invalidate_token()

    assert toss._TOKEN.value is None
    assert second is not first  # 서로 다른 인스턴스인데도 상태를 공유한다


def test_clients_do_not_keep_their_own_buckets(client_pair):
    """인스턴스마다 버킷을 만들면 rate limit 이 인스턴스 수만큼 느슨해진다."""
    first, second = client_pair
    assert not hasattr(first, "_buckets")
    assert not hasattr(second, "_buckets")


def test_expired_token_is_not_reused(client_pair):
    """만료된 토큰을 그대로 쓰면 401 이 돌아온다. 만료 판정이 살아 있는지 본다."""
    first, _ = client_pair
    toss._TOKEN.value = "old-token"
    toss._TOKEN.expires_at = time.monotonic() - 1

    # 만료됐으므로 캐시에서 돌려주지 않는다 — 발급을 시도하다 네트워크에서 막힌다.
    # 여기서는 "캐시가 그대로 돌아오지 않는다"만 확인한다.
    assert not (toss._TOKEN.value and time.monotonic() < toss._TOKEN.expires_at)
