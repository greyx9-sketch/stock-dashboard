"""공공데이터포털(KRX 확정 종가) 연결 확인 스크립트.

두 가지를 한 번에 보여 준다.

  1) KRX 공식 확정 종가가 실제로 내려오는지
  2) 그 종가가 **토스 앱 화면의 기준가와 일치하는지** — 2단계를 시작한 이유가 이것이다.
     토스 일봉 종가는 시간외 체결까지 포함해서 앱 화면 기준가와 어긋난다.

실행:
    python backend/scripts/check_krx.py            # 삼성전자
    python backend/scripts/check_krx.py 000660     # 다른 종목
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

# 이 파일 → scripts → backend. backend 를 경로에 넣어야 `app` 패키지를 찾는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients.krx import KrxClient, KrxError  # noqa: E402
from app.clients.toss import TossClient, TossError  # noqa: E402

DEFAULT_SYMBOL = "005930"
RECENT_DAYS = 5


def won(value: Decimal) -> str:
    return f"{value:,.0f} 원"


async def show(symbol: str) -> int:
    async with KrxClient() as krx:
        quotes = await krx.get_daily_quotes(symbol, limit=RECENT_DAYS)

    if not quotes:
        print(f"\n'{symbol}' 의 시세를 찾지 못했습니다. 국내 종목 코드 6자리가 맞는지 확인해 주세요.\n")
        return 1

    latest = quotes[0]

    print()
    print(f"종목명   {latest.name} ({latest.symbol}, {latest.market})")
    print(f"확정일   {latest.trade_date}  ← KRX 공식 확정 종가 기준일")
    print(f"종가     {won(latest.close)}")
    print(f"전일대비 {latest.change:+,.0f} ({latest.change_rate:+.2f}%)")
    print(f"시고저   {won(latest.open)} / {won(latest.high)} / {won(latest.low)}")
    print(f"거래량   {latest.volume:,.0f} 주")
    print(f"시가총액 {latest.market_cap / 10**12:,.1f} 조원")

    print()
    print(f"최근 {len(quotes)} 거래일")
    for q in quotes:
        print(f"  {q.trade_date}  종가 {q.close:>10,.0f}   등락 {q.change_rate:>+7.2f}%")

    # 핵심 검증: 토스가 랭킹 API 로 주는 공식 기준가와 KRX 확정 종가가 같은 값인가.
    print()
    try:
        async with TossClient() as toss:
            toss_base = await toss.find_official_base_price(symbol, market_country="KR")
            toss_daily = await toss.get_base_price(symbol)
    except (TossError, RuntimeError) as exc:
        print(f"[토스 대조 건너뜀] {exc}")
        return 0

    print("── 토스 값과 대조 ──")
    print(f"  KRX 확정 종가      {won(latest.close)}  ({latest.trade_date})")
    if toss_base is not None:
        match = "일치 ✅" if toss_base.value == latest.close else "불일치 ⚠️"
        print(f"  토스 공식 기준가   {won(toss_base.value)}  ({toss_base.trade_date})  → {match}")
    else:
        print("  토스 공식 기준가   없음 (거래대금 상위 100 종목이 아님)")
    print(f"  토스 일봉 종가     {won(toss_daily.value)}  ({toss_daily.trade_date})  ← 시간외 포함")

    if toss_base is not None and toss_base.value == latest.close:
        print()
        print("  KRX 확정 종가로 토스 앱 화면과 같은 기준가를 만들 수 있음이 확인됐습니다.")
    print()
    return 0


def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SYMBOL
    try:
        return asyncio.run(show(symbol))
    except RuntimeError as exc:
        # config.require() 가 키 없음을 알려주는 경로.
        print(f"\n[설정 필요] {exc}\n")
        return 1
    except KrxError as exc:
        print(f"\n[호출 실패] {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
