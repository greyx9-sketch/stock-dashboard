"""KRX 확정 종가를 받아 DB 에 쌓는 스크립트.

실행:
    python backend/scripts/ingest_krx.py              # 최근 10일 중 아직 없는 날을 채움
    python backend/scripts/ingest_krx.py 30           # 최근 30일(달력 기준)
    python backend/scripts/ingest_krx.py 2026-08-07   # 특정 날짜 하나만

이미 저장된 날은 다시 부르지 않는다. 여러 번 실행해도 안전하다.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

# 이 파일 → scripts → backend. backend 를 경로에 넣어야 `app` 패키지를 찾는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients.krx import KrxError  # noqa: E402
from app.models.base import DATABASE_URL  # noqa: E402
from app.services import krx_ingest  # noqa: E402

DEFAULT_CALENDAR_DAYS = 10


async def run(argument: str | None) -> int:
    if argument and "-" in argument:
        try:
            day = date.fromisoformat(argument)
        except ValueError:
            print(f"\n날짜 형식이 올바르지 않습니다: {argument} (예: 2026-08-07)\n")
            return 1
        print(f"\n{day} 하루치를 받습니다.")
        result = await krx_ingest.ingest_days([day], skip_stored=False)
    else:
        span = int(argument) if argument else DEFAULT_CALENDAR_DAYS
        print(f"\n최근 {span}일 중 아직 저장되지 않은 날을 받습니다.")
        result = await krx_ingest.ingest_recent(span)

    if not result.days:
        print("  받을 것이 없습니다. 해당 기간은 이미 전부 저장돼 있습니다.")
    for day_result in sorted(result.days, key=lambda d: d.day, reverse=True):
        if day_result.is_empty:
            print(f"  {day_result.day}  — 데이터 없음 (휴장일이거나 아직 공개 전)")
        else:
            print(f"  {day_result.day}  {day_result.rows:,} 종목 저장")

    print()
    print(f"이번 실행으로 저장한 행: {result.total_rows:,}")
    print(f"DB 파일: {DATABASE_URL}")
    print()
    print("DB 현황")
    for key, value in krx_ingest.summarize().items():
        label = key.replace("_", " ")
        print(f"  {label:<14} {value:,}" if isinstance(value, int) else f"  {label:<14} {value}")
    print()
    return 0


def main() -> int:
    argument = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        return asyncio.run(run(argument))
    except RuntimeError as exc:
        # config.require() 가 키 없음을 알려주는 경로.
        print(f"\n[설정 필요] {exc}\n")
        return 1
    except KrxError as exc:
        print(f"\n[호출 실패] {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
