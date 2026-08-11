import type { LiveQuote, UsListItem } from './api'

// 미국 종목의 등락률을 구한다.
//
// 국내는 KRX 확정 종가가 기준가라 서버가 등락률까지 계산해 준다. 미국에는 그런 별도 소스가
// 없어서 `/api/prices` 의 기준가가 비어 있고, 대신 토스 랭킹이 기준가를 준다.
//
// 그래서 **현재가는 폴러(5초), 기준가는 랭킹(60초 캐시)** 에서 온다. 랭킹에 실려 온 등락률을
// 그대로 쓰면 현재가만 움직이고 등락률은 멈춰 있는 화면이 된다. 최신 현재가와 기준가로
// 다시 계산해 둘이 어긋나지 않게 한다.

export function usChangeRate(
  item: UsListItem | undefined,
  live: LiveQuote | undefined,
): string | null {
  if (!item) return live?.change_rate ?? null

  const base = Number(item.base_price)
  const last = live ? Number(live.last_price) : Number(item.last_price)

  if (!Number.isFinite(base) || !Number.isFinite(last) || base === 0) {
    // 기준가를 모르면 랭킹이 준 값을 그대로 쓴다(검색 결과에는 기준가가 없다).
    return item.change_rate ?? null
  }
  return (((last - base) / base) * 100).toFixed(2)
}

/** 화면에 보여줄 현재가. 폴러 값이 있으면 그쪽이 더 최신이다. */
export function usLastPrice(
  item: UsListItem | undefined,
  live: LiveQuote | undefined,
): string | undefined {
  if (live) return live.last_price
  // 검색 결과는 시세가 없어 0 이 들어 있다. 그럴 땐 값이 없는 것으로 다룬다.
  if (item && Number(item.last_price) > 0) return item.last_price
  return undefined
}
