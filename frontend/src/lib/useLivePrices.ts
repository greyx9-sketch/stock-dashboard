import { useEffect, useRef, useState } from 'react'
import { fetchLivePrices } from './api'
import type { Country, LiveQuote, MarketState, PricesResponse } from './api'

// 화면이 현재가를 주기적으로 받아 오는 훅.
//
// 주기는 서버가 알려준 장 상태에 맞춘다. 정규장에는 촘촘히, 마감 뒤에는 느슨하게 본다.
// 마감 중에는 값이 바뀌지 않으므로 자주 물어봐야 서버 캐시만 다시 읽을 뿐이다.
//
// 다른 탭을 보고 있을 때는 아예 멈춘다. 브라우저를 켜 둔 채 자리를 비웠는데 계속 호출이
// 나가면 토스 호출 한도를 아무 이유 없이 태운다.

const LIVE_INTERVAL_MS = 5_000
const IDLE_INTERVAL_MS = 30_000

// 아직 못 받은 종목이 있을 때 다시 물어보기까지의 간격. 서버 폴러는 새 종목을 보면 즉시
// 깨어나 받아 오므로, 여기서 30초를 기다리면 화면만 괜히 비어 있게 된다.
const FILLING_INTERVAL_MS = 1_200

// 짧은 간격으로 다시 묻는 횟수의 상한. 상장폐지 등으로 토스가 끝내 주지 않는 종목이 있으면
// 영원히 빠른 폴링에 갇히므로 몇 번만 시도하고 평소 간격으로 돌아간다.
const MAX_FILL_ATTEMPTS = 5

export type LivePrices = {
  bySymbol: Map<string, LiveQuote>
  market: MarketState | null
  error: string | null
  /** 이번 화면에서 아직 한 번도 받지 못했는가. 첫 렌더에서 "—" 를 보여줄지 판단한다. */
  loaded: boolean
}

export function useLivePrices(symbols: string[], country: Country = 'KR'): LivePrices {
  const [data, setData] = useState<PricesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 종목 목록을 문자열로 굳혀 의존성으로 쓴다. 배열을 그대로 쓰면 매 렌더마다 새 배열이라
  // 효과가 계속 다시 돈다.
  const key = symbols.join(',')
  const timer = useRef<number | null>(null)

  useEffect(() => {
    if (!key) {
      setData(null)
      return
    }

    let cancelled = false
    let fillAttempts = 0

    const tick = async () => {
      if (document.visibilityState === 'hidden') {
        schedule(IDLE_INTERVAL_MS)
        return
      }
      try {
        const result = await fetchLivePrices(key.split(','))
        if (cancelled) return
        setData(result)
        setError(result.error)

        const filling = result.missing.length > 0 && fillAttempts < MAX_FILL_ATTEMPTS
        fillAttempts = result.missing.length > 0 ? fillAttempts + 1 : 0
        schedule(
          filling
            ? FILLING_INTERVAL_MS
            : result.markets[country].is_live
              ? LIVE_INTERVAL_MS
              : IDLE_INTERVAL_MS,
        )
      } catch (err) {
        if (cancelled) return
        setError((err as Error).message)
        // 실패해도 멈추지 않는다. 서버가 돌아오면 다시 붙는다.
        schedule(IDLE_INTERVAL_MS)
      }
    }

    const schedule = (ms: number) => {
      if (cancelled) return
      timer.current = window.setTimeout(tick, ms)
    }

    void tick()

    // 다른 탭에 있다가 돌아오면 기다리지 않고 바로 갱신한다.
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      if (timer.current) window.clearTimeout(timer.current)
      void tick()
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      cancelled = true
      if (timer.current) window.clearTimeout(timer.current)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [key, country])

  const bySymbol = new Map<string, LiveQuote>()
  for (const price of data?.prices ?? []) bySymbol.set(price.symbol, price)

  return {
    bySymbol,
    market: data?.markets[country] ?? null,
    error,
    loaded: data !== null,
  }
}
