"""사업보고서 절 추출기 점검 스크립트.

**Anthropic API 를 부르지 않는다.** 돈이 드는 분석을 붙이기 전에 잘라내기가 제대로
되는지 눈으로 확인한다. 미국 쪽 `check_tenk.py` 와 같은 역할이다.

실행:
    python backend/scripts/check_report.py               # 삼성전자·현대차·셀트리온
    python backend/scripts/check_report.py 035720 105560
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients.dart import DartClient, DartError  # noqa: E402
from app.services import dart_corps  # noqa: E402
from app.services.dart_extract import (  # noqa: E402
    DartExtractError,
    extract_sections,
    is_annual_report,
    main_document,
    split_sections,
)

# 업종을 흩어 놓았다. 제조(삼성전자)·완성차(현대차)·바이오(셀트리온).
DEFAULT_SYMBOLS = ["005930", "005380", "068270"]

PREVIEW = 150
LOOKBACK_YEARS = 2


def preview(text: str) -> str:
    if not text:
        return "(없음)"
    head = " ".join(text[:PREVIEW].split())
    tail = " ".join(text[-PREVIEW:].split())
    return f"{head}\n           … 끝 → {tail}"


async def check(symbol: str) -> bool:
    print(f"\n{'=' * 78}\n{symbol}\n{'=' * 78}")

    corp = dart_corps.get_corp(symbol)
    if corp is None:
        print(f"  '{symbol}' 를 DART 매핑에서 찾지 못했습니다.")
        return False
    print(f"  {corp.corp_name} (고유번호 {corp.corp_code})")

    async with DartClient() as dart:
        items = await dart.get_disclosures(
            corp.corp_code,
            begin=date(date.today().year - LOOKBACK_YEARS, 1, 1),
            end=date.today(),
            count=40,
            report_type="A",  # 정기공시
        )
        annual = [d for d in items if is_annual_report(d.report_name)]
        if not annual:
            print("  최근 2년 안에 사업보고서가 없습니다.")
            return False

        target = annual[0]
        print(f"  최신 사업보고서: {target.report_name} · {target.received_date} 접수")
        print(f"  원문: {target.viewer_url}")

        documents = await dart.get_document(target.receipt_no)

    print(f"  ZIP 안 파일 {len(documents)}개")
    body = main_document(documents, target.receipt_no)
    print(f"  본문 {len(body):,}자")

    titles = [t for t, _ in split_sections(body) if t]
    print(f"  대분류 {len(titles)}개: {' / '.join(titles[:6])}{' …' if len(titles) > 6 else ''}")

    try:
        sections = await asyncio.to_thread(extract_sections, body)
    except DartExtractError as exc:
        print(f"  ✗ {exc}")
        return False

    for label, text in (
        ("사업의 내용", sections.business),
        ("경영진단", sections.mdna),
        ("투자자 보호사항", sections.investor),
    ):
        mark = "✓" if text else "✗"
        print(f"\n  {mark} {label}  {len(text):,}자")
        if text:
            print(f"     시작 → {preview(text)}")

    if sections.truncated:
        print(f"\n  ※ 상한에 걸려 잘림: {', '.join(sections.truncated)}")

    # 한글은 대략 2.5자 = 1토큰. 실제 호출 전 비용 감을 잡기 위한 어림값이다.
    approx = sections.total_chars / 2.5
    print(
        f"\n  합계 {sections.total_chars:,}자 ≈ 입력 {approx:,.0f} 토큰"
        f" (Sonnet 5 정가 기준 약 ${approx * 3 / 1_000_000:.2f})"
    )
    # 사업의 내용과 경영진단은 있어야 분석이라 할 만하다. 투자자 보호사항은 없는 회사도 있다.
    return bool(sections.business and sections.mdna)


async def main() -> int:
    symbols = sys.argv[1:] or DEFAULT_SYMBOLS

    if dart_corps.corp_count() == 0:
        print("\nDART 고유번호 매핑이 비어 있습니다. 백엔드를 한 번 띄우면 채워집니다.\n")
        return 1

    results = []
    for symbol in symbols:
        try:
            results.append((symbol, await check(symbol)))
        except DartError as exc:
            print(f"\n  OpenDART 호출 실패: {exc}")
            results.append((symbol, False))

    print(f"\n{'=' * 78}")
    for symbol, ok in results:
        print(f"  {'✓' if ok else '✗'} {symbol}")
    print()
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
