"""SEC EDGAR 클라이언트 — 미국 상장사의 공시와 XBRL 재무.

호출해 보고 확인한 이 API 의 성질:

- **User-Agent 헤더에 이름과 이메일이 없으면 403 이다.** 키는 없지만 신원은 밝혀야 한다.
- **초당 10건이 상한이다.** 넘기면 차단되고, 차단 상태에서 계속 두드리면 더 길어진다.
  실무적으로 8 req/s 로 낮춰 쓴다.
- `company_tickers.json` 하나로 티커→CIK 매핑 전체(약 1만 건)를 받는다. CIK 는 **10자리
  zero-padding** 이 필요하다. 320193 이 아니라 0000320193 으로 불러야 한다.
- 공시 이력(`submissions`)은 객체 목록이 아니라 **열 단위 배열**로 온다.
  `filings.recent.form[i]` 와 `filings.recent.filingDate[i]` 가 같은 건을 가리킨다.
- `companyfacts` 는 회사 하나가 3~4MB 다. 대신 전 연도·전 계정이 한 번에 들어 있어
  호출은 한 번이면 된다.

문서: https://www.sec.gov/about/developer-resources
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.clients.ratelimit import TokenBucket
from app.config import get_settings

WWW_BASE = "https://www.sec.gov"
DATA_BASE = "https://data.sec.gov"

# SEC 공지 상한은 초당 10건이다. 여유를 두고 8 로 잡는다. 차단당하면 복구가 느리다.
REQUESTS_PER_SEC = 8.0


class SecError(Exception):
    """SEC EDGAR 호출 실패."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class UsCompany:
    """티커 → CIK 매핑 한 줄."""

    ticker: str
    cik: str  # 10자리 zero-padding
    name: str


@dataclass(frozen=True)
class UsFiling:
    """미국 공시 한 건."""

    accession_no: str
    form: str  # 10-K, 10-Q, 8-K …
    filing_date: str  # YYYY-MM-DD
    report_date: str  # 보고 기준일
    description: str
    primary_document: str
    cik: str

    @property
    def viewer_url(self) -> str:
        """EDGAR 원문 주소. 접수번호에서 하이픈을 뺀 것이 폴더 이름이다."""
        folder = self.accession_no.replace("-", "")
        cik_plain = self.cik.lstrip("0")
        return f"{WWW_BASE}/Archives/edgar/data/{cik_plain}/{folder}/{self.primary_document}"


def pad_cik(cik: str | int) -> str:
    """CIK 를 10자리로 맞춘다. 이걸 빼먹으면 404 가 난다."""
    return str(cik).strip().lstrip("0").zfill(10)


class SecClient:
    """SEC EDGAR 클라이언트. `async with SecClient() as sec:` 형태로 쓴다."""

    def __init__(self, timeout: float = 60.0):
        settings = get_settings()
        # 이 값이 없으면 SEC 가 403 으로 막는다. 빈 값으로 호출하지 않게 여기서 멈춘다.
        user_agent = settings.require("sec_user_agent")
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": user_agent,
                # 응답이 수 MB 라 압축을 반드시 켠다.
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=True,
        )
        self._bucket = TokenBucket(REQUESTS_PER_SEC)

    async def __aenter__(self) -> "SecClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get_json(self, url: str) -> Any:
        await self._bucket.acquire()
        response = await self._http.get(url)

        if response.status_code == 403:
            raise SecError(
                "SEC 가 403 으로 막았습니다.\n"
                "  User-Agent 에 이름과 이메일이 들어 있어야 합니다. .env 의 SEC_USER_AGENT 를\n"
                "  확인해 주세요. 예: SEC_USER_AGENT=Hong Gildong hong@example.com\n"
                "  초당 10건을 넘겨 일시 차단된 경우일 수도 있습니다. 잠시 뒤 다시 시도해 주세요.",
                status=403,
            )
        if response.status_code == 404:
            raise SecError(
                f"SEC 에 해당 자료가 없습니다(404).\n  주소: {url}\n"
                "  CIK 를 10자리로 맞췄는지 확인해 주세요.",
                status=404,
            )
        if response.status_code != 200:
            raise SecError(
                f"SEC 호출이 HTTP {response.status_code} 로 실패했습니다.\n"
                f"  주소: {url}\n  응답: {response.text[:200]}",
                status=response.status_code,
            )

        try:
            return response.json()
        except ValueError:
            raise SecError(f"SEC 가 JSON 이 아닌 응답을 돌려줬습니다.\n  앞부분: {response.text[:200]}") from None

    # ------------------------------------------------------------------ 티커 매핑

    async def fetch_company_tickers(self) -> list[UsCompany]:
        """티커 → CIK 매핑 전체. 약 1만 건이 한 번에 온다.

        응답이 리스트가 아니라 `{"0": {...}, "1": {...}}` 형태의 사전이다.
        같은 회사가 여러 티커로 등장할 수 있다(클래스 A/B 주식 등).
        """
        payload = await self._get_json(f"{WWW_BASE}/files/company_tickers.json")
        companies: list[UsCompany] = []
        for row in payload.values():
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            companies.append(
                UsCompany(
                    ticker=ticker,
                    cik=pad_cik(row.get("cik_str", "")),
                    name=(row.get("title") or "").strip(),
                )
            )
        return companies

    # ------------------------------------------------------------------ 공시

    async def get_submissions(self, cik: str) -> dict[str, Any]:
        """회사 개요와 최근 공시 이력."""
        return await self._get_json(f"{DATA_BASE}/submissions/CIK{pad_cik(cik)}.json")

    @staticmethod
    def parse_filings(
        submissions: dict[str, Any], *, forms: tuple[str, ...] | None = None, limit: int = 30
    ) -> list[UsFiling]:
        """공시 이력을 건 단위 목록으로 바꾼다.

        SEC 는 이걸 **열 단위 배열**로 준다. `form` 배열과 `filingDate` 배열의 같은 인덱스가
        한 건을 이룬다. 배열 길이가 서로 다를 수 있으므로 가장 짧은 것에 맞춰 돈다.
        """
        recent = (submissions.get("filings") or {}).get("recent") or {}
        cik = pad_cik(submissions.get("cik", ""))

        columns = ("accessionNumber", "form", "filingDate", "reportDate",
                   "primaryDocDescription", "primaryDocument")
        arrays = {name: recent.get(name) or [] for name in columns}
        count = min((len(a) for a in arrays.values()), default=0)

        filings: list[UsFiling] = []
        for i in range(count):
            form = (arrays["form"][i] or "").strip()
            if forms and form not in forms:
                continue
            filings.append(
                UsFiling(
                    accession_no=arrays["accessionNumber"][i],
                    form=form,
                    filing_date=arrays["filingDate"][i],
                    report_date=arrays["reportDate"][i] or "",
                    description=(arrays["primaryDocDescription"][i] or "").strip(),
                    primary_document=arrays["primaryDocument"][i] or "",
                    cik=cik,
                )
            )
            if len(filings) >= limit:
                break
        return filings

    # ------------------------------------------------------------------ 재무 (XBRL)

    async def get_company_facts(self, cik: str) -> dict[str, Any]:
        """회사의 XBRL 사실 전체. 3~4MB 지만 전 연도·전 계정이 한 번에 들어 있다."""
        return await self._get_json(f"{DATA_BASE}/api/xbrl/companyfacts/CIK{pad_cik(cik)}.json")
