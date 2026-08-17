"""매크로 지표 피드 — 이미 운영 중인 `시황` 프로젝트의 공개 결과물을 읽는다.

같은 사용자가 별도로 운영하는 매크로 대시보드가 한국은행 ECOS 와 세인트루이스 연준
FRED 에서 22개 지표를 매일 수집해 GitHub Pages 로 내보내고 있다. 그 결과물을 읽는다.

**왜 ECOS·FRED 를 직접 부르지 않는가.** 기획서에 이렇게 적혀 있다 —
"이미 별도로 관리 중인 매크로 정리와 지표 항목을 맞춰두면 작업이 중복되지 않는다".
같은 수집을 두 번 하면 키가 두 벌 필요하고, 무엇보다 **두 화면의 숫자가 서로 어긋날 수
있다.** 한쪽을 읽으면 항상 일치한다.

성질:
- 645KB 정도의 JSON 하나. 하루 한 번 갱신된다(GitHub Actions).
- 인증이 없다. 공개 정적 파일이다.
- 지표별로 `latest.actual` 이 최신값이고 `unit` 이 단위다. **비율은 0.0275 처럼
  소수로 온다** — 2.75% 로 보이려면 100을 곱해야 한다. 이걸 놓치면 금리가 0.03% 로 뜬다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 시황 프로젝트가 내보내는 공개 주소.
FEED_URL = "https://greyx9-sketch.github.io/macro/data/dashboard.json"

# 645KB 정도다. 이보다 훨씬 크면 다른 파일을 받은 것으로 보고 멈춘다.
MAX_BYTES = 8_000_000


class MacroFeedError(Exception):
    """피드를 받거나 읽는 데 실패."""


@dataclass(frozen=True)
class FeedSeries:
    """지표 한 줄."""

    id: str
    name: str
    unit: str  # ratio / pp / bp / index / percent …
    value: float
    ref_date: str  # 기준일 (YYYY-MM-DD)
    note: str = ""

    @property
    def is_ratio(self) -> bool:
        """0.0275 처럼 소수로 오는 비율인지. 화면에 쓸 때 100을 곱해야 한다."""
        return self.unit == "ratio"


class MacroFeedClient:
    """`async with MacroFeedClient() as feed:` 형태로 쓴다."""

    def __init__(self, timeout: float = 30.0, url: str = FEED_URL):
        self._url = url
        self._http = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def __aenter__(self) -> "MacroFeedClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch(self) -> dict[str, FeedSeries]:
        """지표코드 → 최신값. 값이 없는 지표는 건너뛴다."""
        try:
            response = await self._http.get(self._url)
        except httpx.HTTPError as exc:
            raise MacroFeedError(
                f"매크로 피드를 받지 못했습니다: {exc}\n  주소: {self._url}"
            ) from exc

        if response.status_code != 200:
            raise MacroFeedError(
                f"매크로 피드가 HTTP {response.status_code} 로 응답했습니다.\n"
                f"  주소: {self._url}\n"
                "  시황 프로젝트의 배포가 실패했거나 주소가 바뀌었을 수 있습니다."
            )
        if len(response.content) > MAX_BYTES:
            raise MacroFeedError(
                f"매크로 피드가 예상보다 큽니다({len(response.content) / 1_000_000:.1f}MB)."
            )

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise MacroFeedError("매크로 피드가 JSON 이 아닙니다.") from exc

        series = payload.get("series")
        if not isinstance(series, list) or not series:
            raise MacroFeedError("매크로 피드에 series 가 없습니다. 형식이 바뀐 듯합니다.")

        result: dict[str, FeedSeries] = {}
        for row in series:
            parsed = _parse(row)
            if parsed is not None:
                result[parsed.id] = parsed

        if not result:
            raise MacroFeedError("매크로 피드에서 값이 있는 지표를 찾지 못했습니다.")
        logger.info("매크로 피드 %d개 지표 (생성 %s)", len(result), payload.get("generatedAt"))
        return result


def _parse(row: dict[str, Any]) -> FeedSeries | None:
    series_id = (row.get("id") or "").strip()
    latest = row.get("latest") or {}
    value = latest.get("actual")
    if not series_id or not isinstance(value, (int, float)):
        return None
    return FeedSeries(
        id=series_id,
        name=(row.get("name") or series_id).strip(),
        unit=(row.get("unit") or "").strip(),
        value=float(value),
        ref_date=(latest.get("refDate") or "").strip(),
        note=(row.get("note") or "").strip(),
    )
