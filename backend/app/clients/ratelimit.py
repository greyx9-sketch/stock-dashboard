"""외부 API 호출 속도 제한 도구.

여러 클라이언트(토스, 공공데이터포털, 앞으로 붙을 DART·EDGAR)가 같은 방식으로
초당 호출 수를 지켜야 해서 한 곳에 모아 둔다.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """초당 요청 수를 지키기 위한 토큰 버킷.

    호출 전에 토큰 하나를 소비한다. 없으면 채워질 때까지 기다린다.
    락을 잡은 채로 기다리므로 대기 순서가 뒤섞이지 않는다.
    """

    def __init__(self, rate_per_sec: float):
        self._rate = rate_per_sec
        self._capacity = rate_per_sec
        self._tokens = rate_per_sec
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
            self._updated = now

            if self._tokens < 1:
                await asyncio.sleep((1 - self._tokens) / self._rate)
                self._tokens = 0
                self._updated = time.monotonic()
            else:
                self._tokens -= 1
