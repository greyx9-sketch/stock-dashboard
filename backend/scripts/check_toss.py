"""토스증권 Open API 연결 확인 스크립트.

삼성전자(005930) 현재가를 가져와 사람이 읽기 좋게 출력한다.
토스 앱 화면의 값과 눈으로 대조해서 맞으면 1단계가 끝난 것이다.

실행:
    python backend/scripts/check_toss.py            # 삼성전자
    python backend/scripts/check_toss.py 000660     # 다른 종목
    python backend/scripts/check_toss.py AAPL       # 미국 종목
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# 이 파일 → scripts → backend. backend 를 경로에 넣어야 `app` 패키지를 찾는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients.toss import TossClient, TossError  # noqa: E402

KST = timezone(timedelta(hours=9))
DEFAULT_SYMBOL = "005930"


def format_price(value: Decimal, currency: str) -> str:
    """원화는 정수에 천단위 콤마, 달러는 소수점 두 자리."""
    if currency == "KRW":
        return f"{value:,.0f} 원"
    return f"${value:,.2f}"


def format_change(diff: Decimal, rate: Decimal, currency: str) -> str:
    sign = "+" if diff > 0 else ""
    if currency == "KRW":
        return f"{sign}{diff:,.0f} ({sign}{rate:.2f}%)"
    return f"{sign}{diff:,.2f} ({sign}{rate:.2f}%)"


def format_time(raw: str | None, currency: str) -> str:
    """API 가 준 시각 문자열을 읽기 좋게. 국내 종목은 KST 로 맞춰 보여준다."""
    if not raw:
        return "체결 없음"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if currency == "KRW" and parsed.tzinfo is not None:
        return parsed.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    return parsed.strftime("%Y-%m-%d %H:%M:%S %Z").strip()


async def show(symbol: str) -> int:
    async with TossClient() as toss:
        # 종목명·현재가·전일종가를 각각 다른 API 에서 가져온다.
        # 현재가 응답에는 등락률이 없어서 전일 종가를 캔들에서 따로 구해 직접 계산한다.
        stocks = await toss.get_stocks([symbol])
        prices = await toss.get_prices([symbol])

        if not prices:
            print(f"'{symbol}' 종목의 현재가를 찾지 못했습니다. 심볼을 확인해 주세요.")
            print("  국내는 6자리 숫자(예: 005930), 미국은 티커(예: AAPL) 입니다.")
            return 1

        price = prices[0]
        stock = stocks[0] if stocks else {}
        currency = price.get("currency") or "KRW"
        last_price = Decimal(str(price["lastPrice"]))

        name = stock.get("name") or stock.get("englishName") or "(이름 없음)"
        market = stock.get("market") or "-"

        print()
        print(f"종목명   {name} ({price['symbol']}, {market})")
        print(f"현재가   {format_price(last_price, currency)}")

        # 최근 일봉 2개 = [당일(또는 최근 거래일), 그 직전 거래일].
        # 순서를 믿지 않고 시각 기준으로 정렬한 뒤 두 번째 것을 기준가로 쓴다.
        candles = await toss.get_candles(symbol, interval="1d", count=2)
        candles = sorted(candles, key=lambda c: c["timestamp"], reverse=True)

        if len(candles) >= 2:
            base = Decimal(str(candles[1]["closePrice"]))
            diff = last_price - base
            rate = (diff / base * 100) if base else Decimal(0)
            print(f"전일대비 {format_change(diff, rate, currency)}")
        else:
            print("전일대비 -- (전일 종가를 가져오지 못했습니다)")

        print(f"기준시각 {format_time(price.get('timestamp'), currency)}")
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
    except TossError as exc:
        print(f"\n[호출 실패] {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
