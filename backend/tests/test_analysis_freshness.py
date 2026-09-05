"""분석이 **가장 최근 자료**를 쓰는지.

사용자 질문에서 시작했다 — "가장 최근 자료들로 만드는 방법은 없어?"
연차보고서만 읽으면 카드를 볼 시점에 자료가 반년~1년 묵어 있다.

두 시장의 사정이 정반대라 가져오는 조각이 서로 다르다. 실제 문서를 확인하고 정한 것이라
그 근거를 여기 남긴다(2026-09-06, 삼성전자·AAPL 기준).

| | 사업 설명 | 경영진 설명 |
| --- | --- | --- |
| 국내 반기보고서 | 31,279자 (연차 32,517자와 대등) | **508자 — 법령상 안 싣는다** |
| 미국 10-Q | **0자 — 아예 없다** | 19,575자 (연차 16,600자보다 많다) |

그래서 국내는 사업을 최신 분·반기에서, 미국은 경영진 설명을 최신 10-Q 에서 가져온다.
"""

from __future__ import annotations

import pytest

from app.clients.dart import Disclosure
from app.clients.sec import UsFiling
from app.models.us_analysis import STATUS_OK
from app.services import dart_analysis, tenk_analysis
from app.services.dart_extract import ReportSections
from app.services.tenk_extract import TenKSections, TenQSections


# ---------------------------------------------------------------- 미국


def _us_doc(*, with_quarterly: bool) -> tenk_analysis._Document:
    company = type("C", (), {"name": "Apple Inc.", "ticker": "AAPL", "cik": "0000320193"})()
    annual = UsFiling(
        accession_no="0000320193-25-000123",
        form="10-K",
        filing_date="2025-10-31",
        report_date="2025-09-27",
        description="Annual report",
        primary_document="aapl.htm",
        cik="0000320193",
    )
    quarterly = UsFiling(
        accession_no="0000320193-26-000077",
        form="10-Q",
        filing_date="2026-07-31",
        report_date="2026-06-27",
        description="Quarterly report",
        primary_document="aapl-q3.htm",
        cik="0000320193",
    )
    sections = TenKSections(
        business="아이폰을 만든다.",
        risk_factors="공급망이 몰려 있다.",
        mdna="작년 이야기.",
    )
    return tenk_analysis._Document(
        company=company,
        filing=annual,
        sections=sections,
        quarterly=quarterly if with_quarterly else None,
        quarterly_sections=(
            TenQSections(risk_factors="", mdna="이번 분기 이야기.") if with_quarterly else None
        ),
    )


def test_us_prompt_prefers_the_quarterly_mdna():
    """10-Q 가 있으면 경영진 논의는 **최신 분기 것**을 싣는다.

    연차의 Item 7 은 같은 이야기를 1년 묵은 채로 한다. 둘 다 보내면 토큰만 늘고
    모델이 어느 시점 이야기인지 헷갈린다.
    """
    doc = _us_doc(with_quarterly=True)
    prompt = tenk_analysis._build_prompt(doc, doc.sections)

    assert "이번 분기 이야기." in prompt
    assert "작년 이야기." not in prompt
    # 어느 시점 자료인지 모델에게 밝힌다.
    assert "2026-07-31" in prompt
    # 사업 설명은 10-Q 에 없으므로 연차에서 그대로 온다.
    assert "아이폰을 만든다." in prompt


def test_us_prompt_falls_back_to_the_annual_mdna():
    """10-Q 가 없으면(회계연도 4분기 자리·신규 상장) 연차의 Item 7 로 돌아간다."""
    doc = _us_doc(with_quarterly=False)
    prompt = tenk_analysis._build_prompt(doc, doc.sections)

    assert "작년 이야기." in prompt
    assert "10-Q" not in prompt


def _us_row(quarterly_accession: str):
    row = type("R", (), {})()
    row.status = STATUS_OK
    row.input_tokens = 1500
    row.quarterly_accession = quarterly_accession
    return row


def test_us_new_quarterly_makes_the_card_stale():
    """새 10-Q 가 나왔으면 다시 분석할 값어치가 있다 — 얻는 것이 있기 때문이다."""
    row = _us_row("0000320193-26-000077")
    assert tenk_analysis._should_rerun(
        row, force=False, quarterly_accession="0000320193-26-000199"
    ) is True


def test_us_same_quarterly_does_not_rerun():
    """같은 분기면 다시 부르지 않는다. 얻는 것 없이 돈만 든다."""
    row = _us_row("0000320193-26-000077")
    assert tenk_analysis._should_rerun(
        row, force=False, quarterly_accession="0000320193-26-000077"
    ) is False
    # 10-Q 를 못 읽은 경우(빈 문자열)를 "새것이 나왔다"로 오해하면 안 된다.
    assert tenk_analysis._should_rerun(row, force=False, quarterly_accession="") is False


# ---------------------------------------------------------------- 국내


def _kr_report(*, with_recent: bool) -> dart_analysis._Report:
    corp = type("C", (), {"corp_name": "삼성전자", "stock_code": "005930", "corp_code": "00126380"})()
    annual = Disclosure(
        receipt_no="20260310000001",
        corp_name="삼성전자",
        report_name="사업보고서 (2025.12)",
        received_date="2026-03-10",
        corp_code="00126380",
        stock_code="005930",
        filer_name="삼성전자",
        remark="",
    )
    recent = Disclosure(
        receipt_no="20260814000002",
        corp_name="삼성전자",
        report_name="반기보고서 (2026.06)",
        received_date="2026-08-14",
        corp_code="00126380",
        stock_code="005930",
        filer_name="삼성전자",
        remark="",
    )
    return dart_analysis._Report(
        corp=corp,
        disclosure=annual,
        sections=ReportSections(
            business="작년 사업 설명.", mdna="연차에만 있는 경영진단.", investor="작년 소송."
        ),
        recent=recent if with_recent else None,
        recent_sections=(
            ReportSections(business="올해 사업 설명.", mdna="", investor="올해 소송.")
            if with_recent
            else None
        ),
    )


def test_kr_prompt_takes_business_from_the_recent_report():
    """사업의 내용과 투자자 보호사항은 최신 분·반기에서 온다."""
    report = _kr_report(with_recent=True)
    prompt = dart_analysis._build_prompt(report, report.sections)

    assert "올해 사업 설명." in prompt
    assert "올해 소송." in prompt
    assert "작년 사업 설명." not in prompt
    assert "반기보고서 (2026.06)" in prompt


def test_kr_mdna_always_comes_from_the_annual_report():
    """**경영진단만은 사업보고서 것이다.**

    분·반기보고서에는 법령상 싣지 않는다 — 그 자리에 이렇게 적혀 있다:
    "이사의 경영진단 및 분석의견은 기업공시서식 작성기준에 따라 분ㆍ반기보고서에
    기재하지 않습니다.(사업보고서에 기재 예정)"

    최신 것으로 통째로 갈아타면 이 절이 통째로 사라진다. 그래서 섞어 읽는다.
    """
    report = _kr_report(with_recent=True)
    prompt = dart_analysis._build_prompt(report, report.sections)

    assert "연차에만 있는 경영진단." in prompt


def test_kr_falls_back_when_no_newer_report():
    """사업보고서 직후라 더 새 정기보고서가 없으면 예전대로 동작한다."""
    report = _kr_report(with_recent=False)
    prompt = dart_analysis._build_prompt(report, report.sections)

    assert "작년 사업 설명." in prompt
    assert "작년 소송." in prompt
    assert "반기보고서" not in prompt


def _kr_row(recent_receipt_no: str):
    row = type("R", (), {})()
    row.status = dart_analysis.STATUS_OK
    row.input_tokens = 1500
    row.recent_receipt_no = recent_receipt_no
    return row


def test_kr_new_periodic_makes_the_card_stale():
    row = _kr_row("20260814000002")
    assert dart_analysis._should_rerun(
        row, force=False, recent_receipt_no="20261114000003"
    ) is True


def test_kr_same_periodic_does_not_rerun():
    row = _kr_row("20260814000002")
    assert dart_analysis._should_rerun(
        row, force=False, recent_receipt_no="20260814000002"
    ) is False
    assert dart_analysis._should_rerun(row, force=False, recent_receipt_no="") is False
