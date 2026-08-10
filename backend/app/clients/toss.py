"""토스증권 Open API 클라이언트.

이 프로젝트가 국내·미국 시세를 가져오는 유일한 통로다. 계좌·주문 계열 API 는
프로젝트 범위 밖이므로 아예 만들지 않는다(CLAUDE.md 절대 규칙 2).

문서에서 확인한 제약과 그에 대한 대응:

- 토큰은 client 당 **1개**만 유효하다. 재발급하면 이전 토큰이 즉시 무효가 되므로,
  발급 경로를 락으로 직렬화하지 않으면 서로가 서로의 토큰을 죽인다.
- refresh token 이 없다. 만료되면 같은 엔드포인트로 다시 발급받는다.
- API 그룹별로 초당 요청 수가 제한된다. 그룹마다 토큰 버킷을 따로 둔다.
- 허용 IP 에 없는 곳에서 부르면 403 이다. 이 프로젝트에서 가장 자주 만날 오류라
  원인을 바로 알 수 있게 한국어로 감싸서 올린다.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.clients.ratelimit import TokenBucket
from app.config import get_settings

BASE_URL = "https://openapi.tossinvest.com"

# 그룹별 초당 허용 요청 수. 문서의 Rate Limits 표에서 이 프로젝트가 쓰는 것만 옮겼다.
# 한도는 사전 공지 없이 조정될 수 있으므로 응답 헤더 X-RateLimit-Limit 이 최종 근거다.
RATE_LIMITS: dict[str, float] = {
    "AUTH": 5,
    "STOCK": 5,
    "STOCK_TRADING_TREND": 10,
    "MARKET_INFO": 3,
    "MARKET_DATA": 10,
    "MARKET_DATA_CHART": 5,
    "RANKING": 5,
    "MARKET_INDICATOR_PRICE": 10,
    "MARKET_INDICATOR": 10,
    "MARKET_INDICATOR_CHART": 5,
}

# 429 를 받았을 때 재시도할 최대 횟수. 이 이상은 우리 쪽 호출 설계가 잘못된 것이다.
MAX_RETRY_ON_429 = 3

# 만료 직전에 쓰다가 401 을 맞지 않도록, 실제 만료보다 이만큼 일찍 재발급한다.
TOKEN_EXPIRY_MARGIN_SEC = 60


class TossError(Exception):
    """토스증권 API 호출 실패. 사람이 읽고 다음 행동을 알 수 있는 메시지를 담는다."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class BasePrice:
    """등락률의 기준가. 어느 날 값을 어디서 가져왔는지까지 같이 들고 다닌다.

    출처를 붙이는 이유: 토스는 일봉 종가와 시세 화면의 기준가가 서로 다르다.
    나중에 숫자가 이상해 보일 때 어느 쪽을 쓴 것인지 바로 알 수 있어야 한다.
    """

    value: Decimal
    trade_date: str
    source: str


class TossClient:
    """토스증권 Open API 클라이언트.

    `async with TossClient() as toss:` 형태로 쓴다. 하나를 만들어 재사용해야
    토큰 캐시와 rate limit 이 의미가 있다.
    """

    def __init__(self, timeout: float = 10.0):
        settings = get_settings()
        # 키가 없으면 여기서 멈춘다. 빈 값으로 호출하면 원인 모를 401 로 돌아온다.
        self._client_id = settings.require("toss_client_id")
        self._client_secret = settings.require("toss_client_secret")

        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=timeout)
        self._buckets = {group: TokenBucket(rate) for group, rate in RATE_LIMITS.items()}

        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> "TossClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ 인증

    async def _get_token(self, force_refresh: bool = False) -> str:
        """유효한 액세스 토큰을 돌려준다. 없거나 만료가 가까우면 새로 발급받는다.

        락 안에서 다시 한 번 확인하는 이유: 여러 요청이 동시에 만료를 발견하면
        모두 재발급을 시도하는데, 토큰은 1개만 유효하므로 나중 발급이 앞선 발급을
        무효화해 버린다.
        """
        async with self._token_lock:
            if not force_refresh and self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token

            await self._buckets["AUTH"].acquire()
            response = await self._http.post(
                "/oauth2/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )

            if response.status_code != 200:
                raise self._to_error(response, context="토큰 발급")

            payload = response.json()
            self._access_token = payload["access_token"]
            self._token_expires_at = (
                time.monotonic() + float(payload["expires_in"]) - TOKEN_EXPIRY_MARGIN_SEC
            )
            return self._access_token

    def _invalidate_token(self) -> None:
        self._access_token = None
        self._token_expires_at = 0.0

    # ------------------------------------------------------------------ 공통 호출

    async def _request(
        self,
        path: str,
        *,
        group: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET 요청 하나. rate limit 준수, 429 백오프, 401 재발급 후 1회 재시도를 담당한다."""
        token = await self._get_token()
        retried_after_401 = False

        for attempt in range(MAX_RETRY_ON_429 + 1):
            await self._buckets[group].acquire()
            response = await self._http.get(
                path,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code == 200:
                return response.json().get("result")

            # 토큰이 죽었다. 한 번만 재발급해서 다시 시도한다. 그래도 실패하면 진짜 문제다.
            if response.status_code == 401 and not retried_after_401:
                retried_after_401 = True
                self._invalidate_token()
                token = await self._get_token(force_refresh=True)
                continue

            if response.status_code == 429 and attempt < MAX_RETRY_ON_429:
                await asyncio.sleep(self._retry_delay(response, attempt))
                continue

            raise self._to_error(response, context=path)

        raise TossError(f"{path} 호출이 재시도 한도({MAX_RETRY_ON_429}회)를 넘겼습니다.")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        """429 대기 시간. 서버가 알려준 Retry-After 를 우선하고, 없으면 지수 백오프."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        # 1s → 2s → 4s. jitter 를 섞어 여러 요청이 같은 순간에 몰리는 것을 막는다.
        return (2**attempt) + random.uniform(0, 0.3)

    @staticmethod
    def _to_error(response: httpx.Response, *, context: str) -> TossError:
        """에러 응답을 사람이 읽고 다음 행동을 알 수 있는 예외로 바꾼다."""
        code = None
        message = response.text[:200]
        try:
            error = response.json().get("error") or {}
            code = error.get("code")
            message = error.get("message") or message
        except ValueError:
            pass

        if response.status_code == 403:
            hint = (
                "403 으로 막혔습니다. 허용 IP 문제일 가능성이 가장 높습니다.\n"
                "  tossinvest.com > 설정 > Open API > 허용 IP 관리 에 지금 쓰는 공인 IP 가\n"
                "  등록되어 있는지 확인해 주세요. 가정용 인터넷은 IP 가 바뀔 수 있습니다."
            )
        elif response.status_code == 401:
            hint = "401 인증 실패입니다. .env 의 TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 값을 확인해 주세요."
        elif response.status_code == 429:
            hint = "429 호출 한도 초과입니다. 잠시 뒤 다시 시도해 주세요."
        else:
            hint = f"{context} 호출이 실패했습니다."

        detail = f" (code={code})" if code else ""
        return TossError(
            f"{hint}\n  서버 메시지: {message}{detail}",
            status=response.status_code,
            code=code,
        )

    # ------------------------------------------------------------------ 시세·종목 정보

    async def get_prices(self, symbols: list[str]) -> list[dict[str, Any]]:
        """현재가 조회. 한 번에 최대 200 종목."""
        return await self._request(
            "/api/v1/prices",
            group="MARKET_DATA",
            params={"symbols": ",".join(symbols)},
        )

    async def get_stocks(self, symbols: list[str]) -> list[dict[str, Any]]:
        """종목 기본 정보(종목명, 시장, 통화, 발행주식수 등) 조회."""
        return await self._request(
            "/api/v1/stocks",
            group="STOCK",
            params={"symbols": ",".join(symbols)},
        )

    async def get_candles(
        self,
        symbol: str,
        *,
        interval: str = "1d",
        count: int = 100,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        """캔들(OHLCV) 조회. interval 은 '1m' 또는 '1d', 한 번에 최대 200 봉.

        `before` 는 페이지네이션 상한(inclusive)이다. 이 시각과 같거나 이전인 봉만 돌아온다.
        """
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "count": count}
        if before:
            params["before"] = before
        result = await self._request(
            "/api/v1/candles", group="MARKET_DATA_CHART", params=params
        )
        # 페이지 응답이라 캔들 목록이 한 겹 안에 들어 있다.
        if isinstance(result, dict):
            return result.get("candles", [])
        return result or []

    async def get_market_calendar_kr(self, day: str | None = None) -> dict[str, Any]:
        """국내 장 운영 시간 조회. 전일·당일·익일 3영업일 정보가 돌아온다.

        폴링 주기를 정하는 근거로 쓴다. 장이 닫혀 있는데 5초마다 현재가를 부르는 것은
        호출 한도만 태우는 짓이다.

        휴장일이면 해당 날짜의 `integrated` 가 null 이다. 공휴일표를 직접 관리할 필요가 없다.
        """
        return await self._request("/api/v1/market-calendar/KR", group="MARKET_INFO",
                                   params={"date": day} if day else None)

    async def get_rankings(
        self,
        *,
        ranking_type: str = "MARKET_TRADING_AMOUNT",
        market_country: str = "KR",
        duration: str = "1d",
        count: int = 100,
    ) -> dict[str, Any]:
        """랭킹 조회.

        이 API 만 토스가 계산한 **기준가(basePrice)와 등락률(changeRate)** 을 직접 내려준다.
        다른 시세 API 에는 기준가가 없다. 거래대금 상위 100 종목까지만 덮는다.
        """
        return await self._request(
            "/api/v1/rankings",
            group="RANKING",
            params={
                "type": ranking_type,
                "marketCountry": market_country,
                "duration": duration,
                "count": count,
            },
        )

    async def find_official_base_price(
        self, symbol: str, *, market_country: str = "KR"
    ) -> BasePrice | None:
        """토스가 계산한 공식 기준가를 랭킹에서 찾는다. 없으면 None.

        거래대금 상위 100 종목만 덮으므로 실패가 정상이다. 찾은 경우에는 토스 앱 화면과
        숫자가 정확히 일치한다.
        """
        data = await self.get_rankings(market_country=market_country, count=100)
        for row in data.get("rankings", []):
            if row["symbol"] == symbol:
                return BasePrice(
                    value=Decimal(str(row["price"]["basePrice"])),
                    trade_date=(data.get("rankedAt") or "")[:10],
                    source="토스 공식 기준가(앱 화면과 동일)",
                )
        return None

    async def get_base_price(self, symbol: str) -> BasePrice:
        """등락률의 기준가를 구한다.

        **주의: 이 값은 토스 앱 화면의 기준가와 다를 수 있다.**

        토스 시세 API 에는 기준가 필드가 없어서 직전 거래일 일봉 종가를 쓴다. 그런데
        토스의 일봉 종가는 정규장 종가가 아니라 **시간외(20:00)까지 포함한 마지막 체결가**라,
        토스가 랭킹 API 로 내려주는 공식 기준가와 어긋난다. 삼성전자 2026-08-07 을 예로 들면
        일봉 종가는 235,000 이지만 토스 기준가는 231,000 이다.

        16:00 시간외종가 봉, 15:30 봉, 상/하한가 중간값으로 공식 기준가를 되살려 보려 했으나
        상위 30 종목 검증에서 전부 실패했다. 캔들에 KRX 와 NXT 체결이 섞여 있는 것으로 보인다.
        정확한 정규장 종가는 KRX 공식 일별시세(공공데이터포털)로 따로 받아 채운다.

        그래서 값과 함께 `source` 를 반드시 들고 다닌다. 화면에 어느 기준인지 밝히기 위해서다.
        """
        # 일봉의 시각이 곧 거래일이다. 휴장일을 따로 계산할 필요가 없다.
        days = await self.get_candles(symbol, interval="1d", count=3)
        days.sort(key=lambda c: c["timestamp"], reverse=True)
        if len(days) < 2:
            raise TossError(f"{symbol} 의 직전 거래일 종가를 구할 수 없습니다(일봉 부족).")

        previous = days[1]
        return BasePrice(
            value=Decimal(str(previous["closePrice"])),
            trade_date=previous["timestamp"][:10],
            source="토스 일봉 종가(시간외 포함) — 앱 화면과 다를 수 있음",
        )
