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


# ---------------------------------------------------------------- 프로세스 공유 상태
#
# 토큰과 rate limit 버킷은 **인스턴스가 아니라 프로세스 하나가 공유한다.**
#
# 이 프로젝트는 요청마다 `async with TossClient() as toss:` 로 새 인스턴스를 만든다
# (수급·매크로·관심종목·미국 목록이 각각 그렇게 쓴다). 이것들을 인스턴스에 두면 두 가지가
# 깨진다:
#
#   1. **토큰이 서로를 무효화한다.** 토스는 client_id 당 토큰 하나만 유효하다. 인스턴스마다
#      새로 발급받으면 나중 발급이 앞선 것을 죽여서, 5초마다 도는 폴러가 401 을 맞고 다시
#      발급받고, 그게 또 다른 쪽을 죽이는 일이 반복된다.
#   2. **rate limit 이 지켜지지 않는다.** 버킷이 인스턴스마다 따로면 동시에 뜬 인스턴스
#      수만큼 실제 호출 속도가 배로 뛴다. 실제로 화면을 처음 열 때 매크로·수급·현재가가
#      한꺼번에 나가면서 429 를 맞았다.
#
# httpx 클라이언트는 인스턴스마다 둔다. 공유하면 한쪽의 `aclose()` 가 다른 쪽 요청을
# 끊어 버린다. (연결 재사용까지 노리려면 클라이언트 수명 관리를 따로 설계해야 한다.)

_BUCKETS: dict[str, TokenBucket] = {group: TokenBucket(rate) for group, rate in RATE_LIMITS.items()}


class _TokenCache:
    """프로세스가 하나만 갖는 토큰. 락도 함께 둔다."""

    def __init__(self) -> None:
        self.value: str | None = None
        self.expires_at: float = 0.0
        self.lock = asyncio.Lock()

    def clear(self) -> None:
        self.value = None
        self.expires_at = 0.0


_TOKEN = _TokenCache()


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

    `async with TossClient() as toss:` 형태로 쓴다. 요청마다 새로 만들어도 된다 —
    토큰과 rate limit 버킷은 프로세스 하나가 공유하기 때문이다(위 주석 참고).
    """

    def __init__(self, timeout: float = 10.0):
        settings = get_settings()
        # 키가 없으면 여기서 멈춘다. 빈 값으로 호출하면 원인 모를 401 로 돌아온다.
        self._client_id = settings.require("toss_client_id")
        self._client_secret = settings.require("toss_client_secret")

        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=timeout)
        # 토큰과 버킷은 모듈 수준에서 공유한다. 위 "프로세스 공유 상태" 주석 참고.

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
        async with _TOKEN.lock:
            if not force_refresh and _TOKEN.value and time.monotonic() < _TOKEN.expires_at:
                return _TOKEN.value

            await _BUCKETS["AUTH"].acquire()
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
            _TOKEN.value = payload["access_token"]
            _TOKEN.expires_at = (
                time.monotonic() + float(payload["expires_in"]) - TOKEN_EXPIRY_MARGIN_SEC
            )
            return _TOKEN.value

    @staticmethod
    def _invalidate_token() -> None:
        _TOKEN.clear()

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
            await _BUCKETS[group].acquire()
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
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                # 토스 일반 API 형식: {"error": {"code": ..., "message": ...}}
                code = error.get("code")
                message = error.get("message") or message
            elif isinstance(error, str):
                # OAuth2 표준 형식: {"error": "invalid_client",
                #                    "error_description": "..."}
                # 토큰 엔드포인트가 이 형식으로 답한다. 예전에는 위 dict 형식만 가정해
                # 여기서 AttributeError 가 나면서 진짜 원인이 가려졌다.
                code = error
                message = payload.get("error_description") or message

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

    async def get_market_calendar_us(self, day: str | None = None) -> dict[str, Any]:
        """해외(미국) 장 운영 시간 조회.

        국내와 응답 구조가 다르다. 세션이 `integrated` 안이 아니라 최상위에 있고,
        토스 자체 주간거래인 **데이마켓**(09:00~17:00 KST)이 하나 더 있다.
        """
        return await self._request("/api/v1/market-calendar/US", group="MARKET_INFO",
                                   params={"date": day} if day else None)

    # ------------------------------------------------------------------ 수급 동향
    #
    # 국내 종목 전용이다(미국 종목에 부르면 `unsupported-market`). 다섯 경로가 모두 같은
    # 모양이다 — `count`(최대 100)와 `until`(기준일)을 받고, `{"records": [...], "nextUntil": ...}`
    # 를 **최신순**으로 돌려준다.
    #
    # 갱신 시각이 자료마다 다르다(응답의 `updatedAt` 으로 확인했다):
    #   공매도·대차거래  당일 18~19시    신용거래·투자자별  다음 영업일 04시
    # 그래서 가장 최근 거래일 자료가 아직 안 올라와 있을 수 있다. 날짜를 함께 보여줘야 한다.

    async def _trading_trend(
        self, symbol: str, segment: str, *, count: int, until: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"count": min(max(count, 1), 100)}
        if until:
            params["until"] = until
        payload = await self._request(
            f"/api/v1/stocks/{symbol}/{segment}",
            group="STOCK_TRADING_TREND",
            params=params,
        )
        return payload.get("records") or []

    async def get_investor_trading(
        self, symbol: str, *, count: int = 5, until: str | None = None
    ) -> list[dict[str, Any]]:
        """투자자별 매매동향. 개인·외국인·기관 각각 매수/매도/순매수 **수량(주)**.

        기관은 `breakdown` 으로 금융투자·보험·투신·사모·은행 등으로 더 쪼개져 온다.
        """
        return await self._trading_trend(symbol, "investor-trading", count=count, until=until)

    async def get_program_trades(
        self, symbol: str, *, count: int = 5, until: str | None = None
    ) -> list[dict[str, Any]]:
        """프로그램매매. 차익(arbitrage)·비차익(nonArbitrage)으로 나뉜다."""
        return await self._trading_trend(symbol, "program-trades", count=count, until=until)

    async def get_short_selling(
        self, symbol: str, *, count: int = 5, until: str | None = None
    ) -> list[dict[str, Any]]:
        """공매도. 수량·금액과 각각의 비중(`shortSellingVolumeRate` 는 비율 소수)."""
        return await self._trading_trend(symbol, "short-selling", count=count, until=until)

    async def get_securities_lending(
        self, symbol: str, *, count: int = 5, until: str | None = None
    ) -> list[dict[str, Any]]:
        """대차거래. 체결·상환 수량과 잔고(수량·금액)."""
        return await self._trading_trend(symbol, "securities-lending", count=count, until=until)

    async def get_credit_trades(
        self, symbol: str, *, count: int = 5, until: str | None = None
    ) -> list[dict[str, Any]]:
        """신용거래. 융자(marginLoan)·대주(stockLoan) 각각 신규·상환·잔고와 잔고비율."""
        return await self._trading_trend(symbol, "credit-trades", count=count, until=until)

    async def get_market_indicators(self, symbols: list[str]) -> list[dict[str, Any]]:
        """시장 지표 현재가. **국내 지수·국채만** 제공된다(미국 지수는 없다).

        응답이 리스트다 — 다른 엔드포인트처럼 `{"prices": [...]}` 로 감싸져 있지 않다.
        각 항목에 `symbol`·`lastPrice`만 있고 **기준가나 등락률이 없다.**
        등락률이 필요하면 `get_indicator_candles` 로 전일 종가를 받아 직접 계산한다.

        쓸 수 있는 심볼은 문서가 "심볼 카탈로그" 로만 언급하고 목록을 공개하지 않는다.
        라이브로 확인한 것: `KOSPI`, `KOSDAQ` 은 동작한다. 국채는 KTB3Y·BOND3Y 등
        20가지를 시도했으나 전부 `unsupported-symbol` 이었다 — 국고채 금리는 한국은행
        쪽에서 받는 편이 확실하다.
        """
        return await self._request(
            "/api/v1/market-indicators/prices",
            group="MARKET_INDICATOR_PRICE",
            params={"symbols": ",".join(symbols)},
        )

    async def get_indicator_candles(
        self, symbol: str, *, interval: str = "1d", count: int = 2
    ) -> list[dict[str, Any]]:
        """시장 지표 캔들. 최신순으로 온다(첫 항목이 가장 최근).

        지표 현재가에 기준가가 없어서, 등락률을 계산하려면 이걸로 전일 종가를 받아야 한다.
        """
        payload = await self._request(
            f"/api/v1/market-indicators/{symbol}/candles",
            group="MARKET_INDICATOR_CHART",
            params={"interval": interval, "count": count},
        )
        return payload.get("candles") or []

    async def get_exchange_rate(
        self, base: str = "USD", quote: str = "KRW"
    ) -> dict[str, Any]:
        """환율. 매매기준율(`rate`)과 중간값(`midRate`)이 함께 온다.

        `validFrom`·`validUntil` 로 유효 구간이 오는데 5분 단위다 — 실시간이지만
        초 단위로 움직이지는 않는다. 화면에 기준 시각을 함께 보여주는 편이 정확하다.
        `rateChangeType` 은 UP/DOWN/EQUAL 이다.
        """
        return await self._request(
            "/api/v1/exchange-rate",
            group="MARKET_INFO",
            params={"baseCurrency": base, "quoteCurrency": quote},
        )

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


# ---------------------------------------------------------------- 웹소켓용 토큰

async def get_access_token() -> str:
    """웹소켓 handshake 에 쓸 액세스 토큰.

    **REST 와 같은 토큰을 쓴다.** 토스는 client_id 당 토큰 하나만 유효해서, 웹소켓이
    따로 발급받으면 폴러가 쓰던 토큰이 죽는다. 위 `_TOKEN` 이 프로세스 하나가 공유하는
    캐시이므로 그걸 그대로 꺼내 쓴다.

    웹소켓 인증은 handshake 때 한 번뿐이고, 연결 유지 중 토큰이 만료돼도 끊기지
    않는다(원문). 그래서 연결할 때만 부르면 된다.
    """
    async with TossClient() as client:
        return await client._get_token()
