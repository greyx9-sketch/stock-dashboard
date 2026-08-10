// 백엔드 호출과 응답 타입.
//
// 백엔드는 등락률·현재가 같은 값을 **문자열**로 내려준다. 소수 계산 오차를 막으려고
// 서버에서 Decimal 로 다루기 때문이다. 화면에 그릴 때만 숫자로 바꾼다.

export type Quote = {
  trade_date: string
  symbol: string
  name: string
  market: 'KOSPI' | 'KOSDAQ' | 'KONEX'
  close: number
  change: number
  change_rate: string
  open: number
  high: number
  low: number
  volume: number
  trade_value: number
  market_cap: number
}

export type PricePoint = {
  trade_date: string
  close: number
  open: number
  high: number
  low: number
  volume: number
  change_rate: string
}

export type DataStatus = {
  latest_trade_date: string | null
  oldest_trade_date: string | null
  trading_days: number
  symbols_on_latest: number
  total_rows: number
  source: string
  note: string
}

export type MarketPhase = 'PRE' | 'REGULAR' | 'AFTER' | 'CLOSED' | 'HOLIDAY' | 'UNKNOWN'

export type MarketState = {
  phase: MarketPhase
  label: string
  trade_date: string | null
  next_open: string | null
  session_end: string | null
  is_live: boolean
}

export type LiveQuote = {
  symbol: string
  last_price: string
  base_price: string | null
  base_date: string | null
  change: string | null
  change_rate: string | null
  timestamp: string | null
  age_seconds: number
  stale: boolean
}

export type PricesResponse = {
  market: MarketState
  prices: LiveQuote[]
  missing: string[]
  error: string | null
  last_success_at: string | null
}

export type SortKey = 'market_cap' | 'trade_value' | 'volume' | 'change_rate' | 'close'
export type MarketFilter = 'KOSPI' | 'KOSDAQ' | 'KONEX'

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    // 백엔드는 실패 이유를 detail 에 한국어로 담아 보낸다. 그대로 화면에 보여준다.
    let detail = `요청이 실패했습니다 (HTTP ${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // 응답이 JSON 이 아니면 기본 메시지를 쓴다.
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export function fetchStatus() {
  return get<DataStatus>('/api/meta')
}

export function fetchStocks(options: {
  sort: SortKey
  market: MarketFilter | null
  limit: number
}) {
  const params = new URLSearchParams({
    sort: options.sort,
    limit: String(options.limit),
  })
  if (options.market) params.set('market', options.market)
  return get<Quote[]>(`/api/stocks?${params}`)
}

export function searchStocks(keyword: string) {
  return get<Quote[]>(`/api/stocks/search?q=${encodeURIComponent(keyword)}`)
}

/** 종목의 가장 최근 확정 시세. 현재가는 fetchLivePrices 가 따로 준다. */
export function fetchStockDetail(symbol: string) {
  return get<Quote>(`/api/stocks/${symbol}`)
}

export function fetchDailyPrices(symbol: string, days = 90) {
  return get<PricePoint[]>(`/api/stocks/${symbol}/daily?days=${days}`)
}

/** 현재가. 서버가 미리 받아 둔 값을 읽어 오므로 이 호출 자체는 외부 API 를 기다리지 않는다. */
export function fetchLivePrices(symbols: string[]) {
  return get<PricesResponse>(`/api/prices?symbols=${symbols.join(',')}`)
}
