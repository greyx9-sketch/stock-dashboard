"""공공데이터포털 — 금융위원회 주식시세정보 클라이언트.

KRX 정규장 **확정 종가**를 가져오는 통로다. 토스증권 API 에는 기준가 필드가 없고,
토스 일봉 종가는 시간외(20:00) 체결까지 포함한 값이라 앱 화면의 등락률과 어긋난다.
여기서 받는 `clpr`(종가)이 토스 앱 기준가와 일치하는 것을 삼성전자 2026-08-07 로 확인했다
(KRX 231,000 = 토스 기준가 231,000, 토스 일봉 종가는 235,000).

문서에서 확인한 제약과 그에 대한 대응:

- **실시간이 아니다.** 갱신은 하루 1회, 기준일자로부터 **다음 영업일 오후 1시 이후**다.
  금요일 데이터는 다음 월요일에 올라온다. 장중 등락률에는 쓸 수 없고, 확정 종가 아카이브용이다.
- 개발계정의 일일 호출 한도는 10,000 건이다. 종목마다 매번 부르면 금방 태운다.
  종가는 하루에 한 번만 바뀌므로 받아서 DB 에 넣고 재사용하는 것을 전제로 만들었다.
- 인증키는 발급 화면에 Encoding / Decoding 두 가지가 있다. 어느 쪽을 붙여넣어도 되도록
  항상 한 번 디코딩해서 쓴다(아래 `_normalize_service_key` 주석 참고).
- 키가 틀리면 JSON 이 아니라 XML 에러 봉투가 돌아온다. 그대로 두면 JSON 파싱 오류로
  둔갑해 원인을 알 수 없으므로 따로 잡아 한국어로 알려 준다.

스펙 출처: https://www.data.go.kr/data/15094808/openapi.do
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

import httpx

from app.clients.ratelimit import TokenBucket
from app.config import get_settings
from app.clock import today_kst

logger = logging.getLogger(__name__)

BASE_URL = "https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService"

# 공공데이터포털은 초당 한도를 공개하지 않는다(초과 시 에러코드 23). 확정 종가는 급할 일이
# 없으므로 넉넉하게 낮춰 잡는다. 막히는 것보다 느린 편이 낫다.
REQUESTS_PER_SEC = 5.0

# 한 번에 받아올 수 있는 행 수의 상한. 이보다 크게 요청해도 서버가 잘라낸다.
MAX_ROWS_PER_PAGE = 1000

# 에러코드 → 사람이 읽고 다음 행동을 알 수 있는 안내. 포털 "오픈API 에러코드 안내" 표에서
# 이 프로젝트가 실제로 만날 만한 것만 옮겼다.
ERROR_HINTS: dict[str, str] = {
    "20": (
        "이 API 에 대한 이용 권한이 확인되지 않습니다.\n"
        "  data.go.kr > 마이페이지 > 데이터활용 > Open API 에서 '금융위원회_주식시세정보'\n"
        "  활용신청이 승인 상태인지 확인해 주세요."
    ),
    "22": (
        "오늘 호출 한도(개발계정 10,000건)를 다 썼습니다.\n"
        "  자정에 초기화됩니다. 같은 종목을 반복 호출하고 있지 않은지 확인해 주세요."
    ),
    "23": "초당 호출 한도를 넘겼습니다. 잠시 뒤 다시 시도해 주세요.",
    "30": (
        "등록되지 않은 인증키입니다.\n"
        "  .env 의 DATA_GO_KR_API_KEY 값을 확인해 주세요. data.go.kr 발급 화면의\n"
        "  '일반 인증키' 를 통째로 복사해 붙여넣으면 됩니다."
    ),
    "31": "인증키 사용 기한이 만료되었습니다. data.go.kr 에서 이용 기간을 갱신해 주세요.",
}


class KrxError(Exception):
    """공공데이터포털 호출 실패. 사람이 읽고 다음 행동을 알 수 있는 메시지를 담는다."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DailyQuote:
    """KRX 확정 일별 시세 한 줄. 숫자는 전부 Decimal 로 들고 다닌다.

    부동소수(float)를 쓰면 231000.00000000003 같은 값이 생겨 원 단위 비교가 어긋난다.
    """

    trade_date: str  # YYYY-MM-DD
    symbol: str  # 단축코드 6자리
    isin: str
    name: str
    market: str  # KOSPI / KOSDAQ / KONEX
    close: Decimal  # 정규장 확정 종가 — 등락률의 기준가로 쓰는 값
    change: Decimal  # 전일 대비
    change_rate: Decimal  # 등락률 (%)
    open: Decimal
    high: Decimal
    low: Decimal
    volume: Decimal
    trade_value: Decimal  # 거래대금
    listed_shares: Decimal
    market_cap: Decimal


class KrxClient:
    """공공데이터포털 주식시세정보 클라이언트.

    `async with KrxClient() as krx:` 형태로 쓴다. 인증은 요청 파라미터의 serviceKey 하나뿐이라
    토스와 달리 토큰 발급 절차가 없다.
    """

    def __init__(self, timeout: float = 20.0):
        settings = get_settings()
        raw_key = settings.require("data_go_kr_api_key")
        self._service_key = self._normalize_service_key(raw_key)

        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=timeout)
        self._bucket = TokenBucket(REQUESTS_PER_SEC)

    @staticmethod
    def _normalize_service_key(raw: str) -> str:
        """인증키를 항상 '디코딩된' 형태로 맞춘다.

        포털은 같은 키를 Encoding(`%2F` 같은 이스케이프 포함)과 Decoding 두 가지로 보여준다.
        httpx 가 파라미터를 다시 URL 인코딩하므로, Encoding 키를 그대로 넘기면 `%` 가 `%25` 로
        한 번 더 바뀌어 인증이 깨진다. 미리 한 번 풀어 두면 어느 쪽을 붙여넣어도 동작한다.
        (디코딩 키는 base64 문자만 쓰므로 다시 풀어도 그대로다.)
        """
        return unquote(raw.strip())

    async def __aenter__(self) -> "KrxClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ 공통 호출

    async def _request(self, path: str, params: dict[str, Any]) -> list[dict[str, str]]:
        """GET 요청 하나. 응답 봉투를 벗겨 item 목록만 돌려준다."""
        _, rows = await self._request_page(path, params)
        return rows

    async def _request_page(
        self, path: str, params: dict[str, Any]
    ) -> tuple[int, list[dict[str, str]]]:
        """GET 요청 하나. (전체 건수, item 목록) 을 돌려준다.

        페이지를 넘기려면 전체 건수가 필요해서 `_request` 와 나눠 두었다.
        """
        await self._bucket.acquire()
        response = await self._http.get(
            path,
            params={"serviceKey": self._service_key, "resultType": "json", **params},
        )

        if response.status_code != 200:
            raise KrxError(
                f"공공데이터포털 호출이 HTTP {response.status_code} 로 실패했습니다.\n"
                f"  서버 응답: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError:
            # 인증키가 틀리면 JSON 대신 XML 에러 봉투가 온다. 거기서 코드를 뽑아낸다.
            raise KrxError(self._describe_xml_error(response.text)) from None

        header = payload.get("response", {}).get("header", {})
        code = header.get("resultCode")
        if code not in ("00", "0"):
            hint = ERROR_HINTS.get(str(code), header.get("resultMsg", "알 수 없는 오류"))
            raise KrxError(f"공공데이터포털이 오류를 돌려줬습니다(코드 {code}).\n  {hint}", code=str(code))

        body = payload.get("response", {}).get("body", {}) or {}
        total = int(body.get("totalCount") or 0)

        # 결과가 없으면 items 가 빈 문자열로 온다. 이 API 의 오래된 관행이다.
        items = body.get("items") or {}
        if not isinstance(items, dict):
            return total, []
        rows = items.get("item") or []
        return total, (rows if isinstance(rows, list) else [rows])

    @staticmethod
    def _describe_xml_error(text: str) -> str:
        """XML 에러 봉투에서 코드를 찾아 한국어 안내로 바꾼다."""
        code_match = re.search(r"<returnReasonCode>(\d+)</returnReasonCode>", text)
        msg_match = re.search(r"<returnAuthMsg>([^<]+)</returnAuthMsg>", text)
        code = code_match.group(1) if code_match else None

        if code and code in ERROR_HINTS:
            return f"공공데이터포털이 요청을 거부했습니다(코드 {code}).\n  {ERROR_HINTS[code]}"
        detail = msg_match.group(1) if msg_match else text[:200]
        return (
            "공공데이터포털이 JSON 대신 오류를 돌려줬습니다. 인증키 문제일 가능성이 높습니다.\n"
            f"  서버 메시지: {detail}\n"
            "  .env 의 DATA_GO_KR_API_KEY 를 확인해 주세요."
        )

    # ------------------------------------------------------------------ 일별 시세

    async def get_daily_quotes(
        self,
        symbol: str,
        *,
        begin: date | None = None,
        end: date | None = None,
        limit: int = 30,
    ) -> list[DailyQuote]:
        """한 종목의 일별 확정 시세를 **최신순**으로 돌려준다.

        `begin`/`end` 를 주지 않으면 최근 `limit` 영업일이 담기도록 넉넉히 거슬러 올라간다.
        휴장일 때문에 달력 일수와 영업일 수가 다르므로 여유를 두고 요청한 뒤 잘라 낸다.
        """
        params: dict[str, Any] = {
            "likeSrtnCd": symbol,
            "numOfRows": min(max(limit * 2, 10), MAX_ROWS_PER_PAGE),
            "pageNo": 1,
        }
        if begin is None and end is None:
            # 영업일 기준 limit 일을 확보하려면 주말·공휴일을 감안해 대략 1.6배가 필요하다.
            begin = today_kst() - timedelta(days=int(limit * 1.6) + 10)
        if begin is not None:
            params["beginBasDt"] = begin.strftime("%Y%m%d")
        if end is not None:
            params["endBasDt"] = end.strftime("%Y%m%d")

        rows = await self._request("/getStockPriceInfo", params)
        quotes = [self._to_quote(row) for row in rows if row.get("srtnCd") == symbol]

        # **요청한 창 밖의 행은 버린다** — 신선도 가드(`_only_for` 와 같은 이유).
        # 포털이 조회 기간을 무시하고 오래된 구간을 돌려주면, 정렬해서 맨 앞을 집는
        # 아래 코드가 **1년 전 종가를 "가장 최근 종가"로** 내놓는다. 비어 있지 않다는
        # 것만으로는 그것을 걸러낼 수 없다.
        window_begin = begin.isoformat() if begin else None
        window_end = end.isoformat() if end else None
        quotes = [
            q
            for q in quotes
            if (window_begin is None or q.trade_date >= window_begin)
            and (window_end is None or q.trade_date <= window_end)
        ]

        quotes.sort(key=lambda q: q.trade_date, reverse=True)
        return quotes[:limit]

    async def get_latest_close(self, symbol: str) -> DailyQuote:
        """가장 최근에 확정된 종가 한 줄. 등락률 기준가로 쓰는 값이다.

        오늘 장중이라면 이 값은 **어제 종가가 아니라 그저께 종가**일 수 있다.
        오늘 데이터는 내일 오후 1시 이후에 올라오기 때문이다. `trade_date` 를 반드시 같이 본다.
        """
        quotes = await self.get_daily_quotes(symbol, limit=1)
        if not quotes:
            raise KrxError(
                f"'{symbol}' 의 확정 종가를 찾지 못했습니다.\n"
                "  국내 종목 코드 6자리가 맞는지 확인해 주세요(예: 005930).\n"
                "  상장폐지되었거나 최근 휴장이 길었다면 조회 기간을 늘려야 할 수 있습니다."
            )
        return quotes[0]

    async def get_quotes_for_date(self, day: date) -> list[DailyQuote]:
        """그날 거래된 **전 종목**의 확정 시세를 돌려준다. 휴장일이면 빈 목록.

        하루치가 약 2,900 종목이고 한 번에 1,000 행까지 받으므로 하루 = 3 호출이다.
        종목마다 따로 부르면 2,900 호출이 나가 일일 한도(10,000)를 하루 세 번이면 태운다.
        날짜 단위로 받아서 DB 에 넣는 것이 이 API 를 쓰는 유일하게 온전한 방법이다.
        """
        collected: list[dict[str, str]] = []
        page = 1
        params = {"basDt": day.strftime("%Y%m%d"), "numOfRows": MAX_ROWS_PER_PAGE}

        while True:
            total, rows = await self._request_page(
                "/getStockPriceInfo", {**params, "pageNo": page}
            )
            collected.extend(rows)
            # 마지막 페이지는 요청한 것보다 적게 온다. 그것과 전체 건수 도달을 둘 다 본다.
            if not rows or len(collected) >= total or len(rows) < MAX_ROWS_PER_PAGE:
                break
            page += 1
            if page > 20:  # 하루 2만 종목은 있을 수 없다. 무한 루프 방지용 안전장치.
                raise KrxError(f"{day} 조회가 페이지 한도를 넘겼습니다. 응답이 이상합니다.")

        return [self._to_quote(row) for row in self._only_for(collected, day)]

    @staticmethod
    def _only_for(rows: list[dict[str, str]], day: date) -> list[dict[str, str]]:
        """요청한 날짜의 행만 남긴다 — **신선도 가드**.

        비어 있는지만 보는 검사는 **비어 있지 않은 틀린 값**을 못 잡는다. 응답에 행이 있고
        종가 필드도 차 있으면 지금까지는 그대로 저장했는데, 그 행이 우리가 요청한 날짜의
        것인지는 아무도 확인하지 않았다. 포털이 `basDt` 를 무시하고 다른 날짜를 돌려주면:

        - 행은 자기 날짜로 저장된다(데이터 자체는 맞다). 그런데
        - 적재 보고는 "요청한 그날 N 행을 받았다"고 **거짓을 말하고**,
        - `stored_dates` 는 그날이 여전히 비어 있다고 보므로 **매일 같은 날을 다시 받는다**.
          일일 한도 10,000 건을 조용히 태우는 길이다.

        그래서 문 앞에서 막는다. 한 줄도 안 맞으면 값을 지어내지 않고 **이유를 말하며
        멈춘다**(`scheduler` 가 실패로 기록하고 헬스체크가 알린다). 일부만 섞여 있으면
        맞는 것만 남기고 경고를 남긴다 — 하루치가 통째로 날아가는 것이 더 나쁘다.

        휴장일(응답이 빈 목록)은 여기서 걸리지 않는다. 남길 것도 버릴 것도 없기 때문이다.
        """
        wanted = day.strftime("%Y%m%d")
        matched = [r for r in rows if (r.get("basDt") or "").strip() == wanted]
        if len(matched) == len(rows):
            return matched

        seen = sorted({(r.get("basDt") or "").strip() or "(빈 값)" for r in rows})[:5]
        if not matched:
            raise KrxError(
                f"{day} 를 요청했는데 응답에 그날 자료가 한 줄도 없습니다"
                f"(받은 기준일자: {', '.join(seen)}).\n"
                "  포털이 요청한 날짜를 무시하고 있습니다. 저장하지 않고 멈춥니다."
            )
        logger.warning(
            "%s 응답에 다른 날짜가 섞여 있어 %d/%d 행만 남깁니다(받은 기준일자: %s)",
            day, len(matched), len(rows), ", ".join(seen),
        )
        return matched

    @staticmethod
    def _to_quote(row: dict[str, str]) -> DailyQuote:
        """응답 한 줄을 DailyQuote 로 바꾼다.

        모든 숫자가 문자열로 오고, 등락률은 ".22" 처럼 앞자리 0 이 빠진 형태다.
        Decimal 은 이 표기를 그대로 받아들인다.
        """
        raw = row.get("basDt", "")
        trade_date = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else raw

        def num(field: str) -> Decimal:
            value = (row.get(field) or "").strip()
            return Decimal(value) if value else Decimal(0)

        return DailyQuote(
            trade_date=trade_date,
            symbol=row.get("srtnCd", ""),
            isin=row.get("isinCd", ""),
            name=row.get("itmsNm", ""),
            market=row.get("mrktCtg", ""),
            close=num("clpr"),
            change=num("vs"),
            change_rate=num("fltRt"),
            open=num("mkp"),
            high=num("hipr"),
            low=num("lopr"),
            volume=num("trqu"),
            trade_value=num("trPrc"),
            listed_shares=num("lstgStCnt"),
            market_cap=num("mrktTotAmt"),
        )
