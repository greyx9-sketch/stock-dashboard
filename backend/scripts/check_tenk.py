"""10-K 섹션 추출기 점검 스크립트.

**Anthropic API 를 부르지 않는다.** 돈이 드는 분석을 붙이기 전에, 잘라내기가 제대로
되는지부터 눈으로 확인하기 위한 것이다. 목차 몇 줄이 아니라 본문이 잡혔는지,
경계가 엉뚱한 데서 끊기지 않았는지 앞뒤 문장을 보고 판단한다.

실행:
    python backend/scripts/check_tenk.py                # AAPL JPM WMT
    python backend/scripts/check_tenk.py NVDA KO
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 이 파일 → scripts → backend. backend 를 경로에 넣어야 `app` 패키지를 찾는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients.sec import SecClient, SecError  # noqa: E402
from app.services import sec_companies  # noqa: E402
from app.services.tenk_extract import (  # noqa: E402
    TenKExtractError,
    extract_sections,
    html_to_text,
)

# JPM 은 위험요인이 방대하고, WMT 는 회계연도가 어긋난다. 함정 검출용으로 기본에 넣었다.
DEFAULT_TICKERS = ["AAPL", "JPM", "WMT"]

PREVIEW = 160


def preview(text: str) -> str:
    """앞뒤를 잘라 한 줄로. 경계가 맞는지 보는 용도다."""
    if not text:
        return "(없음)"
    head = " ".join(text[:PREVIEW].split())
    tail = " ".join(text[-PREVIEW:].split())
    return f"{head}\n           … 끝 → {tail}"


async def check(ticker: str) -> bool:
    print(f"\n{'=' * 78}\n{ticker}\n{'=' * 78}")

    company = sec_companies.get_company(ticker)
    if company is None:
        print(f"  '{ticker}' 를 SEC 티커 목록에서 찾지 못했습니다.")
        return False
    print(f"  {company.name} (CIK {company.cik})")

    async with SecClient() as sec:
        submissions = await sec.get_submissions(company.cik)
        filings = SecClient.parse_filings(submissions, forms=("10-K",), limit=1)
        if not filings:
            print("  10-K 가 없습니다. 외국 발행사(20-F)이거나 신규 상장일 수 있습니다.")
            return False

        filing = filings[0]
        print(f"  최신 10-K: {filing.filing_date} 접수 · 기준일 {filing.report_date}")
        print(f"  원문: {filing.viewer_url}")

        html = await sec.get_filing_document(filing)

    print(f"  내려받은 크기: {len(html) / 1_000_000:.1f} MB")

    try:
        text = await asyncio.to_thread(html_to_text, html)
    except TenKExtractError as exc:
        print(f"  본문 변환 실패: {exc}")
        return False

    print(f"  태그 제거 후: {len(text):,} 자")

    sections = extract_sections(text)
    if sections.is_empty:
        print("  ✗ 세 항목을 하나도 찾지 못했습니다.")
        return False

    for label, body in (
        ("Item 1  사업", sections.business),
        ("Item 1A 위험요인", sections.risk_factors),
        ("Item 7  MD&A", sections.mdna),
    ):
        mark = "✓" if body else "✗"
        print(f"\n  {mark} {label}  {len(body):,} 자")
        if body:
            print(f"     시작 → {preview(body)}")

    if sections.mdna_from_reference:
        print("\n  ※ Item 7 은 참조 형식이라 MD&A 본문을 자체 제목으로 찾았습니다.")
    if sections.truncated:
        print(f"  ※ 상한에 걸려 잘림: {', '.join(sections.truncated)}")

    # 4글자 ≈ 1토큰. 실제 호출 전에 비용 감을 잡기 위한 어림값이다.
    approx_tokens = sections.total_chars / 4
    print(
        f"\n  합계 {sections.total_chars:,} 자 ≈ 입력 {approx_tokens:,.0f} 토큰"
        f" (Sonnet 5 도입가 기준 약 ${approx_tokens * 2 / 1_000_000:.2f})"
    )
    return len(sections.found) == 3


async def main() -> int:
    tickers = [t.upper() for t in sys.argv[1:]] or DEFAULT_TICKERS

    if sec_companies.company_count() == 0:
        print("\nSEC 티커 매핑이 비어 있습니다. 백엔드를 한 번 띄우면 자동으로 채워집니다.\n")
        return 1

    results = []
    for ticker in tickers:
        try:
            results.append((ticker, await check(ticker)))
        except SecError as exc:
            print(f"\n  SEC 호출 실패: {exc}")
            results.append((ticker, False))

    print(f"\n{'=' * 78}")
    for ticker, ok in results:
        print(f"  {'✓' if ok else '✗'} {ticker}")
    print()
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
