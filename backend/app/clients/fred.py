"""FRED(세인트루이스 연준) 클라이언트 — 이 프로젝트에서는 WTI 유가 하나만 쓴다.

매크로 지표 대부분은 `macro_feed.py` 로 `시황` 프로젝트의 결과물을 읽는다. 유가는
그쪽에서 수집하지 않아 여기서만 직접 받는다.

호출 형태는 사용자가 이미 운영 중인 `시황` 프로젝트의 FRED 코드와 같게 맞췄다 —
같은 키를 쓰고 같은 엔드포인트를 부르므로, 한쪽에서 동작하면 다른 쪽도 동작한다.

성질:
- 키는 무료다. https://fredaccount.stlouisfed.org/apikeys
- 값이 없는 날은 `"."` 로 온다(공휴일·주말). 숫자로 바꾸려 하면 예외가 난다.
- 응답은 오래된 날짜부터 온다. 최신값은 마지막 항목이다.

문서: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

# WTI 원유 현물 가격(달러/배럴), 일별. 시황 프로젝트가 쓰는 것과 같은 계열 체계다.
WTI_SERIES = "DCOILWTICO"

# 최근 값 몇 개만 받는다. 연휴가 길어도 마지막 실측값이 들어오도록 넉넉히 잡는다.
RECENT_LIMIT = 10


class FredError(Exception):
    """FRED 호출 실패."""


@dataclass(frozen=True)
class FredPoint:
    series_id: str
    date: str  # YYYY-MM-DD
    value: float


class FredClient:
    """`async with FredClient() as fred:` 형태로 쓴다."""

    def __init__(self, timeout: float = 30.0):
        # 키가 없으면 여기서 멈춘다. 빈 값으로 부르면 원인을 알기 어려운 400 이 온다.
        self._key = get_settings().require("fred_api_key")
        self._http = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> "FredClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_latest(self, series_id: str) -> FredPoint:
        """가장 최근 실측값 하나. 값이 비어 있는 날(`.`)은 건너뛴다."""
        params = {
            "series_id": series_id,
            "api_key": self._key,
            "file_type": "json",
            # 최신순으로 받아 앞에서부터 훑는다. 오래된 순으로 받으면 전부 뒤져야 한다.
            "sort_order": "desc",
            "limit": RECENT_LIMIT,
        }
        try:
            response = await self._http.get(OBSERVATIONS_URL, params=params)
        except httpx.HTTPError as exc:
            raise FredError(f"FRED 호출에 실패했습니다: {exc}") from exc

        if response.status_code == 400:
            raise FredError(
                "FRED 가 요청을 거절했습니다(400).\n"
                "  .env 의 FRED_API_KEY 가 올바른지 확인해 주세요. 32자 영숫자입니다.\n"
                "  https://fredaccount.stlouisfed.org/apikeys 에서 무료로 발급받습니다."
            )
        if response.status_code != 200:
            raise FredError(f"FRED 호출이 HTTP {response.status_code} 로 실패했습니다.")

        try:
            payload = response.json()
        except ValueError as exc:
            raise FredError("FRED 가 JSON 이 아닌 응답을 돌려줬습니다.") from exc

        for obs in payload.get("observations") or []:
            raw = (obs.get("value") or "").strip()
            # 값이 없는 날은 "." 이다. 주말·공휴일이 이렇게 온다.
            if raw in ("", "."):
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            return FredPoint(series_id=series_id, date=obs.get("date", ""), value=value)

        raise FredError(
            f"'{series_id}' 의 최근 {RECENT_LIMIT}건에서 실측값을 찾지 못했습니다."
        )

    async def get_wti(self) -> FredPoint:
        """WTI 유가(달러/배럴)."""
        return await self.get_latest(WTI_SERIES)
