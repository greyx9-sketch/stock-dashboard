"""토스증권 웹소켓 — 체결이 일어나는 **그 순간** 현재가를 받는다.

폴링은 "지금 얼마냐"를 1초마다 되묻는 방식이라, 아무리 줄여도 왕복 시간(0.3~1초)이
바닥이고 그 사이 체결은 안 보인다. 웹소켓은 반대로 서버가 밀어 준다.

**이 파일은 값을 저장하지 않는다.** 받은 체결을 콜백으로 넘길 뿐이고, 캐시·장 상태·
관심 종목은 전부 `services/price_poller.py` 가 그대로 들고 있다. 폴링을 걷어내지 않고
**얹은** 이유는 아래 "왜 폴링을 남겨 두는가"에 적었다.

## 스펙 (2026-08-24 AsyncAPI 원문 확인)

`wss://openapi-ws.tossinvest.com/ws/v1` · handshake 때 `Authorization: Bearer` 헤더.

- **구독은 선언형(full-replace)이다.** JSON 배열 하나가 곧 현재 구독 전체다. subscribe/
  unsubscribe 액션이 없고, 배열에서 빠진 것은 자동 해제된다. 빈 배열은 전체 해제.
- **받는 프레임**: `{"type":"message","topic":"trade:us:AAPL","data":{"price":"243.26",
  "volume":"8","timestamp":"...","currency":"USD"}}`
- **구독 직후 스냅샷을 주지 않는다.** 다음 체결부터 푸시된다 → 첫 값은 REST 로 받아야 한다.
- **푸시는 모든 세션에서 온다.** 미국은 프리·정규·애프터·데이마켓, 국내는 KRX 정규장과
  NXT 프리·정규·애프터 합산이다.
- **keepalive**: 클라이언트가 180초간 아무것도 안 보내면 서버가 끊는다. 서버가 보내주는
  데이터는 이 타이머를 리셋하지 **않는다** — 데이터를 받는 중에도 우리가 보내야 한다.
  JSON 이 아닌 순수 텍스트 `PING`(대문자)에 `{"type":"pong"}` 이 온다. 60초 권장.
- **한도**: 계정당 동시 연결 **2개**, 연결당 구독 **100건**, 선언 **5회/초**.
- **LOSSY**: 밀리면 중간 프레임이 유실된다. 누적 거래량을 합산으로 재구성할 수 없다 —
  그래서 여기서는 체결가만 쓴다.

## 왜 폴링을 남겨 두는가

셋 다 웹소켓만으로는 메울 수 없는 구멍이다.

1. **구독 직후에는 값이 안 온다.** 다음 체결까지 화면이 비어 있을 수 없다.
2. **구독은 100종목까지다.** 국내 목록 화면 하나가 50종목을 보고, 관심종목이 60개까지
   담긴다. 넘치는 몫은 REST 가 맡는다.
3. **연결이 살아 있는 채로 조용해질 수 있다.** LOSSY 이고 sequence 도 없어서 우리가
   유실을 감지할 방법이 없다. 30초짜리 REST 안전망이 그 경우를 덮는다.

## 동시 연결 2개 — 개발 중에 조심할 것

계정당 2개다. **서버 하나 + 개발 PC 하나면 이미 꽉 찬다.** 셋째를 열면 가장 오래된
연결이 소리 없이 끊긴다(별도 close code 없이). 로컬에서 시험할 때 배포 서버의 연결이
끊길 수 있다는 뜻이다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from websockets.asyncio.client import connect

from app.clients.toss import get_access_token

logger = logging.getLogger(__name__)

WS_URL = "wss://openapi-ws.tossinvest.com/ws/v1"

# 연결당 구독 한도(codes 합산). 넘치면 too-many-topics 로 선언 전체가 거부된다.
MAX_TOPICS = 100

# keepalive 주기(초). 서버는 180초 침묵이면 끊는다. 원문 권장이 60초다.
PING_INTERVAL_SEC = 60.0

# 선언 빈도 한도는 5회/초. 화면을 옮겨 다니면 관심 종목이 연달아 바뀌므로,
# 한도의 1/5 로 넉넉히 눌러 둔다. 1초 늦게 구독해도 사람은 알아채지 못한다.
DECLARE_MIN_GAP_SEC = 1.0

# 재연결 백오프. 원문 권장대로 1→2→4… 에 jitter 를 섞는다.
BACKOFF_START_SEC = 1.0
BACKOFF_MAX_SEC = 60.0

# 한 번에 밀려 들어오는 프레임을 담아 둘 큐 크기. 체결이 몰릴 때 읽기가 잠깐 밀려도
# 끊기지 않게 넉넉히 잡는다. 어차피 LOSSY 라 오래된 프레임은 값어치가 없다.
MAX_QUEUE = 512

# 다시 선언해도 같은 이유로 또 거부되는 것들. 목록에서 빼야 한다(원문 명시).
PERMANENT_REJECTS = ("stock-not-found", "symbol-market-mismatch")


class TossTradeFeed:
    """체결 푸시를 받아 콜백으로 넘긴다. 연결·재연결·구독 선언을 혼자 책임진다.

    `on_trade(symbol, price, timestamp)` 는 **이벤트 루프 안에서** 불린다. 무거운 일을
    하면 수신이 밀리고, 밀리면 프레임이 유실된다(LOSSY). 캐시에 값을 넣는 정도만 한다.
    """

    def __init__(self, on_trade: Callable[[str, Decimal, str | None], None]) -> None:
        self._on_trade = on_trade
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

        # 구독하고 싶은 것과 실제로 확정된 것. 둘이 다를 수 있다(한도·거부).
        self._wanted: dict[str, list[str]] = {"kr": [], "us": []}
        self._subscribed: set[str] = set()
        # 거부당한 종목. 다시 넣으면 또 거부되므로 선언에서 뺀다.
        self._rejected: set[str] = set()

        self._dirty = asyncio.Event()
        self._connected = False
        self._last_message_at: datetime | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------------ 밖에서 보는 것

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_message_at(self) -> datetime | None:
        return self._last_message_at

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def subscribed(self) -> set[str]:
        """실제로 구독이 확정된 종목."""
        return {topic.split(":", 2)[2] for topic in self._subscribed if topic.count(":") >= 2}

    def covers(self, symbols: list[str]) -> bool:
        """이 종목들이 **전부** 실시간으로 들어오고 있는가.

        하나라도 빠지면 거짓이다. 그 하나 때문에 REST 를 빠른 주기로 돌려야 한다.
        빈 목록은 참이다 — 받을 것이 없으면 빠뜨린 것도 없다.
        """
        if not symbols:
            return True
        return self._connected and set(symbols) <= self.subscribed

    def set_symbols(self, kr: list[str], us: list[str]) -> None:
        """구독할 종목을 갈아 끼운다. **폴러의 이벤트 루프에서만 부른다.**

        한도(100건)를 넘으면 앞에서부터 자른다. 폴러가 최근에 요청된 순서로 넘겨주므로
        잘리는 것은 가장 오래 방치된 종목이고, 그 몫은 REST 가 계속 맡는다.
        """
        kr = [s for s in kr if s not in self._rejected]
        us = [s for s in us if s not in self._rejected]

        # 두 시장 합산이 한도다. 한쪽이 많다고 다른 쪽을 굶기지 않도록 번갈아 담는다.
        picked_kr, picked_us = _share_quota(kr, us, MAX_TOPICS)

        fresh = {"kr": picked_kr, "us": picked_us}
        if fresh == self._wanted:
            return
        self._wanted = fresh
        self._dirty.set()

    # ------------------------------------------------------------------ 수명 관리

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="toss-trade-feed")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self._connected = False

    # ------------------------------------------------------------------ 연결 루프

    async def _run(self) -> None:
        backoff = BACKOFF_START_SEC
        while not self._stopping:
            try:
                # **연결할 때마다 토큰을 새로 가져온다.** 헤더는 handshake 때 한 번만
                # 쓰이므로, 오래 끊겨 있다 붙을 때 낡은 토큰이면 401 로 막힌다.
                token = await get_access_token()
                async with connect(
                    WS_URL,
                    additional_headers={"Authorization": f"Bearer {token}"},
                    open_timeout=15,
                    close_timeout=5,
                    max_queue=MAX_QUEUE,
                ) as ws:
                    logger.info("토스 웹소켓 연결됨")
                    backoff = BACKOFF_START_SEC
                    self._connected = True
                    self._last_error = None
                    # 새 연결에는 구독이 없다. 무조건 다시 선언한다.
                    self._subscribed.clear()
                    self._dirty.set()
                    await self._session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning("토스 웹소켓 끊김 — %s", self._last_error)
            finally:
                self._connected = False
                self._subscribed.clear()

            if self._stopping:
                break
            # jitter 를 섞는다. 서버가 한 번 재시작했을 때 모두가 같은 순간에 몰리지
            # 않게 하려는 것이다(원문 권장).
            await asyncio.sleep(backoff * (1.0 + random.random() * 0.3))
            backoff = min(backoff * 2, BACKOFF_MAX_SEC)

    async def _session(self, ws: Any) -> None:
        """연결 하나가 사는 동안. 읽기가 본류이고 나머지는 곁다리 작업이다."""
        helpers = [
            asyncio.create_task(self._ping_loop(ws), name="toss-ws-ping"),
            asyncio.create_task(self._declare_loop(ws), name="toss-ws-declare"),
        ]
        try:
            async for raw in ws:
                self._handle(raw)
        finally:
            for task in helpers:
                task.cancel()
            await asyncio.gather(*helpers, return_exceptions=True)

    async def _ping_loop(self, ws: Any) -> None:
        """60초마다 텍스트 `PING`.

        **서버가 보내주는 데이터는 침묵 타이머를 리셋하지 않는다.** 체결이 쏟아지는
        중에도 우리가 보내지 않으면 180초 뒤에 끊긴다.
        """
        while True:
            await asyncio.sleep(PING_INTERVAL_SEC)
            await ws.send("PING")

    async def _declare_loop(self, ws: Any) -> None:
        """관심 종목이 바뀌면 구독 전체를 다시 선언한다(full-replace)."""
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            # 화면을 옮겨 다니면 연달아 바뀐다. 몰아서 한 번만 보낸다.
            await asyncio.sleep(DECLARE_MIN_GAP_SEC)
            self._dirty.clear()
            await ws.send(json.dumps(self._declaration(), ensure_ascii=False))

    def _declaration(self) -> list[dict[str, Any]]:
        """지금 구독하고 싶은 것 전체. 이 배열 하나가 곧 구독 전부다."""
        out: list[dict[str, Any]] = []
        for market in ("kr", "us"):
            codes = self._wanted[market]
            if codes:
                out.append({"type": f"trade:{market}", "codes": codes})
        return out

    # ------------------------------------------------------------------ 프레임 처리

    def _handle(self, raw: str | bytes) -> None:
        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            return  # 텍스트 PING 에 대한 응답 외에는 올 것이 없다. 조용히 넘긴다.
        if not isinstance(frame, dict):
            return

        kind = frame.get("type")
        if kind == "message":
            self._handle_trade(frame)
        elif kind == "subscriptions":
            self._handle_ack(frame)
        elif kind == "error":
            self._handle_error(frame)
        # pong 은 살아 있다는 뜻뿐이라 할 일이 없다.

    def _handle_trade(self, frame: dict[str, Any]) -> None:
        topic = frame.get("topic") or ""
        parts = topic.split(":", 2)
        if len(parts) != 3:
            return
        symbol = parts[2]

        data = frame.get("data") or {}
        try:
            price = Decimal(str(data["price"]))
        except (KeyError, InvalidOperation, TypeError):
            return

        self._last_message_at = datetime.now(timezone.utc)
        self._on_trade(symbol, price, data.get("timestamp"))

    def _handle_ack(self, frame: dict[str, Any]) -> None:
        self._subscribed = set(frame.get("subscribed") or [])

        rejected = frame.get("rejected") or []
        drop: set[str] = set()
        for item in rejected:
            if not isinstance(item, dict):
                continue
            if item.get("code") in PERMANENT_REJECTS:
                # 원문: 원인을 고치기 전에는 다시 넣어도 또 거부된다. 목록에서 뺀다.
                # 거부 항목의 종목은 `target` 에 full key 로 온다 — `trade:kr:999999`.
                target = str(item.get("target") or "")
                if target.count(":") >= 2:
                    drop.add(target.split(":", 2)[2])

        if drop:
            logger.info("웹소켓이 거부한 종목(REST 로만 받는다): %s", ", ".join(sorted(drop)))
            self._rejected |= drop
            # 거부된 것을 뺀 채로 다시 선언한다.
            self.set_symbols(
                [s for s in self._wanted["kr"] if s not in drop],
                [s for s in self._wanted["us"] if s not in drop],
            )

    def _handle_error(self, frame: dict[str, Any]) -> None:
        error = frame.get("error") or {}
        code = error.get("code")
        self._last_error = f"{code}: {error.get('message')}"[:200]

        if code == "rate-limit-exceeded":
            # 선언이 너무 잦았다. 잠시 뒤 다시 선언한다(원문: 약 1초 대기).
            self._dirty.set()
        elif code == "too-many-topics":
            # 100건을 넘겼다. 절반으로 줄여 다시 선언한다 — 잘린 몫은 REST 가 맡는다.
            logger.warning("웹소켓 구독 한도 초과 — 절반으로 줄인다")
            half = MAX_TOPICS // 2
            kr, us = _share_quota(self._wanted["kr"], self._wanted["us"], half)
            self.set_symbols(kr, us)
        elif code == "server-shutdown":
            # 곧 끊긴다. 읽기 루프가 끝나면 바깥 루프가 알아서 다시 붙는다.
            logger.info("토스 웹소켓 서버 배포 중 — 재연결한다")
        else:
            logger.warning("토스 웹소켓 오류 — %s", self._last_error)


def _share_quota(kr: list[str], us: list[str], quota: int) -> tuple[list[str], list[str]]:
    """구독 한도를 두 시장이 나눠 갖는다.

    한쪽이 한도를 통째로 먹지 않게 절반씩 주되, **남는 몫은 상대에게 넘긴다.**
    국내만 보고 있을 때 미국 몫 50자리를 비워 두면 그냥 손해다.
    """
    if len(kr) + len(us) <= quota:
        return list(kr), list(us)

    half = quota // 2
    kr_take = min(len(kr), half)
    us_take = min(len(us), quota - kr_take)
    # 상대가 덜 썼으면 남은 자리를 마저 가져간다.
    kr_take = min(len(kr), quota - us_take)
    return list(kr[:kr_take]), list(us[:us_take])
