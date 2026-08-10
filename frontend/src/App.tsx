import { useEffect, useState } from 'react'
import { fetchStatus, fetchStocks, searchStocks } from './lib/api'
import type { DataStatus, MarketFilter, Quote, SortKey } from './lib/api'
import { StockTable } from './components/StockTable'
import { StockDetailPanel } from './components/StockDetailPanel'

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'market_cap', label: '시가총액' },
  { key: 'trade_value', label: '거래대금' },
  { key: 'volume', label: '거래량' },
  { key: 'change_rate', label: '등락률' },
]

const MARKET_OPTIONS: { key: MarketFilter | null; label: string }[] = [
  { key: null, label: '전체' },
  { key: 'KOSPI', label: 'KOSPI' },
  { key: 'KOSDAQ', label: 'KOSDAQ' },
]

const LIST_LIMIT = 50

export default function App() {
  const [status, setStatus] = useState<DataStatus | null>(null)
  const [stocks, setStocks] = useState<Quote[]>([])
  const [sort, setSort] = useState<SortKey>('market_cap')
  const [market, setMarket] = useState<MarketFilter | null>(null)
  const [keyword, setKeyword] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchStatus().then(setStatus).catch(() => setStatus(null))
  }, [])

  // 검색어가 있으면 검색 결과를, 없으면 정렬된 목록을 보여준다.
  // 입력할 때마다 호출하지 않도록 250ms 기다렸다가 보낸다.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    const trimmed = keyword.trim()
    const timer = setTimeout(() => {
      const request = trimmed
        ? searchStocks(trimmed)
        : fetchStocks({ sort, market, limit: LIST_LIMIT })

      request
        .then((result) => {
          if (cancelled) return
          setStocks(result)
          // 목록이 바뀌었는데 선택한 종목이 사라졌으면 첫 종목으로 옮긴다.
          setSelected((current) => {
            if (current && result.some((s) => s.symbol === current)) return current
            return result[0]?.symbol ?? null
          })
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message)
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }, trimmed ? 250 : 0)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [sort, market, keyword])

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">국내 주식 시세</h1>
        <p className="mt-1 text-sm text-neutral-400">
          {status?.latest_trade_date ? (
            <>
              KRX 확정 종가 <span className="tabular">{status.latest_trade_date}</span> 기준 ·{' '}
              <span className="tabular">{status.symbols_on_latest.toLocaleString()}</span> 종목
            </>
          ) : (
            '데이터 현황을 불러오는 중…'
          )}
        </p>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="종목명 또는 코드 검색"
          className="w-56 rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm placeholder:text-neutral-600 focus:border-neutral-600 focus:outline-none"
        />

        {keyword.trim() === '' && (
          <>
            <div className="flex gap-1">
              {SORT_OPTIONS.map((option) => (
                <button
                  key={option.key}
                  onClick={() => setSort(option.key)}
                  className={`rounded-md px-2.5 py-1.5 text-sm transition-colors ${
                    sort === option.key
                      ? 'bg-neutral-100 text-neutral-900'
                      : 'bg-neutral-900 text-neutral-300 hover:bg-neutral-800'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>

            <div className="flex gap-1">
              {MARKET_OPTIONS.map((option) => (
                <button
                  key={option.label}
                  onClick={() => setMarket(option.key)}
                  className={`rounded-md px-2.5 py-1.5 text-sm transition-colors ${
                    market === option.key
                      ? 'bg-neutral-100 text-neutral-900'
                      : 'bg-neutral-900 text-neutral-300 hover:bg-neutral-800'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </>
        )}

        {loading && <span className="text-xs text-neutral-500">불러오는 중…</span>}
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_420px]">
        <StockTable stocks={stocks} selectedSymbol={selected} onSelect={setSelected} />
        <aside>{selected && <StockDetailPanel symbol={selected} />}</aside>
      </div>

      {status && (
        <footer className="mt-8 border-t border-neutral-800 pt-4 text-xs text-neutral-500">
          <p>출처: {status.source}</p>
          <p className="mt-1">{status.note}</p>
          <p className="mt-1">
            보유 기간 {status.oldest_trade_date} ~ {status.latest_trade_date} ·{' '}
            {status.trading_days} 거래일 · {status.total_rows.toLocaleString()} 행
          </p>
        </footer>
      )}
    </div>
  )
}
