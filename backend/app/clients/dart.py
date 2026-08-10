"""OpenDART(전자공시시스템) 클라이언트.

국내 종목의 공시·재무 데이터가 전부 여기서 나온다.

호출해 보고 확인한 이 API 의 성질:

- **오류도 HTTP 200 으로 온다.** 실패 여부는 본문의 `status` 필드로만 알 수 있다.
  status 를 안 보고 그냥 파싱하면 "등록되지 않은 인증키"를 빈 목록으로 착각하게 된다.
- **종목코드로는 조회할 수 없다.** DART 는 자체 고유번호(`corp_code`, 8자리)를 쓴다.
  이 매핑은 `corpCode.xml` 한 번의 호출로 전부 받을 수 있고(ZIP 안의 XML, 약 3.5MB,
  11만여 건 중 상장사 약 4천 건), 자주 바뀌지 않으므로 DB 에 넣어 두고 쓴다.
- `status: "013"` 은 오류가 아니라 **조회 결과 없음**이다. 빈 목록으로 다룬다.
- 일일 호출 한도는 20,000 건이다.

문서: https://opendart.fss.or.kr/intro/main.do
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import date
from typing import Any
from xml.etree import ElementTree

import httpx

from app.clients.ratelimit import TokenBucket
from app.config import get_settings

BASE_URL = "https://opendart.fss.or.kr/api"

# 일일 한도가 20,000 건이므로 초당 상한 자체는 여유가 있다. 다만 목록을 여러 페이지 돌 때
# 몰아치지 않도록 완만하게 잡는다.
REQUESTS_PER_SEC = 5.0

# 결과 없음. 오류가 아니다.
NO_DATA = "013"

# status 코드 → 사람이 읽고 다음 행동을 알 수 있는 안내.
ERROR_HINTS: dict[str, str] = {
    "010": (
        "등록되지 않은 인증키입니다.\n"
        "  .env 의 DART_API_KEY 값을 확인해 주세요. opendart.fss.or.kr 에서 발급받은\n"
        "  40자리 키여야 합니다."
    ),
    "011": (
        "사용할 수 없는 인증키입니다.\n"
        "  이메일 인증을 마치지 않았거나 키가 정지된 상태일 수 있습니다.\n"
        "  opendart.fss.or.kr > 인증키 신청/관리 에서 상태를 확인해 주세요."
    ),
    "012": "접근할 수 없는 IP 입니다. OpenDART 에 등록된 IP 인지 확인해 주세요.",
    "014": "요청한 파일이 존재하지 않습니다.",
    "020": (
        "오늘 호출 한도(20,000건)를 초과했습니다.\n"
        "  자정에 초기화됩니다. 같은 요청을 반복하고 있지 않은지 확인해 주세요."
    ),
    "021": "한 번에 조회할 수 있는 회사 수(100건)를 초과했습니다.",
    "100": "요청 값이 올바르지 않습니다. 날짜 형식이나 고유번호를 확인해 주세요.",
    "101": "부적절한 접근입니다.",
    "800": "OpenDART 가 시스템 점검 중입니다. 잠시 뒤 다시 시도해 주세요.",
    "901": "인증키 계정의 개인정보 보유기간이 만료되었습니다. 재동의가 필요합니다.",
}


# 공시 유형(pblntf_ty). 이 필터가 없으면 목록이 쓸모없어진다 — 삼성전자의 경우 최근 1년 반
# 공시 약 3,400 건 중 3,328 건이 임원 소유상황 같은 지분공시라 정기보고서가 묻힌다.
REPORT_TYPES: dict[str, str] = {
    "A": "정기공시",  # 사업·반기·분기보고서
    "B": "주요사항보고",  # 유상증자, 자기주식, 합병 등
    "C": "발행공시",
    "D": "지분공시",  # 임원·주요주주 소유상황, 대량보유
    "E": "기타공시",
    "F": "외부감사관련",
    "G": "펀드공시",
    "H": "자산유동화",
    "I": "거래소공시",  # 수시공시, 자율공시
    "J": "공정위공시",
}


class DartError(Exception):
    """OpenDART 호출 실패. 사람이 읽고 다음 행동을 알 수 있는 메시지를 담는다."""

    def __init__(self, message: str, *, status: str | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class CorpEntry:
    """고유번호 매핑 한 줄. 상장사만 담는다."""

    corp_code: str  # DART 고유번호 8자리
    corp_name: str
    stock_code: str  # 단축코드 6자리
    modify_date: str  # YYYYMMDD


@dataclass(frozen=True)
class Disclosure:
    """공시 한 건."""

    receipt_no: str  # 접수번호. 원문 링크를 만드는 열쇠다.
    corp_code: str
    corp_name: str
    stock_code: str
    report_name: str
    filer_name: str  # 제출인
    received_date: str  # YYYY-MM-DD
    remark: str  # 비고(정정·첨부 등 표시)

    @property
    def viewer_url(self) -> str:
        """DART 원문 보기 주소. 접수번호만 있으면 만들 수 있다."""
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={self.receipt_no}"


class DartClient:
    """OpenDART 클라이언트. `async with DartClient() as dart:` 형태로 쓴다."""

    def __init__(self, timeout: float = 30.0):
        settings = get_settings()
        self._key = settings.require("dart_api_key")
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=timeout)
        self._bucket = TokenBucket(REQUESTS_PER_SEC)

    async def __aenter__(self) -> "DartClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ 공통 호출

    async def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """JSON 엔드포인트 호출. 결과가 없으면(013) None 을 돌려준다."""
        await self._bucket.acquire()
        response = await self._http.get(path, params={"crtfc_key": self._key, **params})

        if response.status_code != 200:
            raise DartError(
                f"OpenDART 호출이 HTTP {response.status_code} 로 실패했습니다.\n"
                f"  서버 응답: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError:
            raise DartError(
                "OpenDART 가 JSON 이 아닌 응답을 돌려줬습니다.\n"
                f"  앞부분: {response.text[:200]}"
            ) from None

        status = str(payload.get("status", ""))
        if status == NO_DATA:
            return None
        if status and status != "000":
            hint = ERROR_HINTS.get(status, payload.get("message", "알 수 없는 오류"))
            raise DartError(
                f"OpenDART 가 오류를 돌려줬습니다(status {status}).\n  {hint}", status=status
            )
        return payload

    # ------------------------------------------------------------------ 고유번호 매핑

    async def fetch_corp_codes(self) -> list[CorpEntry]:
        """상장사의 종목코드 → 고유번호 매핑 전체를 받는다.

        응답이 ZIP 파일이다(JSON 이 아니다). 안에 XML 하나가 들어 있다.
        11만여 건 중 종목코드가 있는 상장사만 남긴다 — 비상장사는 이 프로젝트가 쓰지 않는다.
        """
        await self._bucket.acquire()
        response = await self._http.get("/corpCode.xml", params={"crtfc_key": self._key})

        if response.status_code != 200:
            raise DartError(f"고유번호 파일 요청이 HTTP {response.status_code} 로 실패했습니다.")

        # 인증키가 틀리면 ZIP 대신 XML 오류 문서가 온다. 앞 두 바이트로 구분한다.
        if response.content[:2] != b"PK":
            status = self._status_from_xml(response.text)
            hint = ERROR_HINTS.get(status or "", "인증키를 확인해 주세요.")
            raise DartError(
                f"고유번호 파일을 받지 못했습니다(status {status}).\n  {hint}", status=status
            )

        archive = zipfile.ZipFile(io.BytesIO(response.content))
        xml_bytes = archive.read(archive.namelist()[0])
        root = ElementTree.fromstring(xml_bytes)

        entries: list[CorpEntry] = []
        for node in root.findall("list"):
            stock_code = (node.findtext("stock_code") or "").strip()
            if not stock_code:
                continue  # 비상장사
            entries.append(
                CorpEntry(
                    corp_code=(node.findtext("corp_code") or "").strip(),
                    corp_name=(node.findtext("corp_name") or "").strip(),
                    stock_code=stock_code,
                    modify_date=(node.findtext("modify_date") or "").strip(),
                )
            )
        return entries

    @staticmethod
    def _status_from_xml(text: str) -> str | None:
        try:
            return (ElementTree.fromstring(text).findtext("status") or "").strip() or None
        except ElementTree.ParseError:
            return None

    # ------------------------------------------------------------------ 공시

    async def get_disclosures(
        self,
        corp_code: str,
        *,
        begin: date,
        end: date,
        count: int = 30,
        final_only: bool = True,
        report_type: str | None = None,
    ) -> list[Disclosure]:
        """한 회사의 공시 목록을 최신순으로 돌려준다.

        `final_only` 는 최종보고서만 볼지 여부다. 켜 두면 나중에 정정된 원본이 빠져
        목록이 훨씬 읽기 쉬워진다.

        `report_type` 은 공시 유형 한 글자다(REPORT_TYPES 참고). 비우면 전체를 본다.
        """
        params: dict[str, Any] = {
            "corp_code": corp_code,
            "bgn_de": begin.strftime("%Y%m%d"),
            "end_de": end.strftime("%Y%m%d"),
            "page_count": min(max(count, 1), 100),
            "page_no": 1,
            "last_reprt_at": "Y" if final_only else "N",
        }
        if report_type:
            if report_type not in REPORT_TYPES:
                raise DartError(f"알 수 없는 공시 유형입니다: {report_type}")
            params["pblntf_ty"] = report_type

        payload = await self._get_json("/list.json", params)
        if payload is None:
            return []  # 해당 기간에 공시가 없다. 오류가 아니다.

        return [self._to_disclosure(row) for row in payload.get("list") or []]

    @staticmethod
    def _to_disclosure(row: dict[str, str]) -> Disclosure:
        raw = row.get("rcept_dt", "")
        received = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else raw
        return Disclosure(
            receipt_no=row.get("rcept_no", ""),
            corp_code=row.get("corp_code", ""),
            corp_name=row.get("corp_name", ""),
            stock_code=row.get("stock_code", ""),
            report_name=(row.get("report_nm") or "").strip(),
            filer_name=(row.get("flr_nm") or "").strip(),
            received_date=received,
            remark=(row.get("rm") or "").strip(),
        )

    # ------------------------------------------------------------------ 기업개황

    async def get_company(self, corp_code: str) -> dict[str, Any] | None:
        """기업 개황(대표자, 설립일, 결산월, 주소 등). 없으면 None."""
        payload = await self._get_json("/company.json", {"corp_code": corp_code})
        if payload is None:
            return None
        return {k: v for k, v in payload.items() if k not in ("status", "message")}
