import { useEffect, useMemo, useState } from 'react'
import { fetchStatus, fetchStocks, searchStocks } from '../lib/api'
import type { DataStatus, MarketFilter, Quote, SortKey } from '../lib/api'
import { useLivePrices } from '../lib/useLivePrices'
import { formatTimestamp } from '../lib/format'
import { StockTable } from '../components/StockTable'
import { StockDetailPanel } from '../components/StockDetailPanel'
import { MarketBadge } from '../components/MarketBadge'
import { Segmented } from '../components/ui/Segmented'
import { ErrorBox, Loading } from '../components/ui/Status'

const SORT_OPTIONS = [
  { value: 'market_cap', label: '시가총액' },
  { value: 'trade_value', label: '거래대금' },
  { value: 'volume', label: '거래량' },
  { value: 'change_rate', label: '등락률' },
] as const satisfies readonly { value: SortKey; label: string }[]

// '전체'는 시장 필터를 안 거는 것이라 API 로는 null 이다. 화면 상태로는 다른 선택지와
// 같은 자격이어야 해서 'ALL' 이라는 이름을 주고 호출 직전에 null 로 바꾼다.
const MARKET_OPTIONS = [
  { value: 'ALL', label: '전체' },
  { value: 'KOSPI', label: 'KOSPI' },
  { value: 'KOSDAQ', label: 'KOSDAQ' },
] as const satisfies readonly { value: MarketFilter | 'ALL'; label: string }[]

type MarketChoice = (typeof MARKET_OPTIONS)[number]['value']

const LIST_LIMIT = 50

/**
 * 확정 종가 자동 수집이 잘 돌고 있는지 한 줄로 알린다.
 * 데이터가 갱신되지 않을 때 사용자가 원인을 스스로 알 수 있어야 한다.
 */
function describeCollection(collection: DataStatus['collection']): string {
  if (collection.running) return '자동 수집: 지금 받는 중…'

  const next = collection.next_run_at
    ? `다음 수집 ${formatTimestamp(collection.next_run_at)}`
    : '다음 수집 예정 없음'

  if (collection.last_error) {
    return `자동 수집 실패 — ${collection.last_error} · ${next}`
  }
  if (!collection.last_run_at) {
    return `자동 수집 대기 중 · ${next}`
  }

  const added = collection.last_run_rows
    ? `${collection.last_run_days}거래일 ${collection.last_run_rows.toLocaleString()}행 추가`
    : '새로 받을 것 없음'
  return `자동 수집 정상 · 마지막 ${formatTimestamp(collection.last_run_at)} (${added}) · ${next}`
}

export function KrMarket() {
  const [status, setStatus] = useState<DataStatus | null>(null)
  const [stocks, setStocks] = useState<Quote[]>([])
  const [sort, setSort] = useState<SortKey>('market_cap')
  const [market, setMarket] = useState<MarketChoice>('ALL')
  const [keyword, setKeyword] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // 데이터 현황을 주기적으로 다시 본다. 자동 수집이 새 거래일을 채우면
  // (평일 13:20 무렵) 화면이 그걸 알아채고 목록까지 새로 불러와야 하기 때문이다.
  useEffect(() => {
    let cancelled = false
    const load = () => {
      fetchStatus()
        .then((result) => {
          if (!cancelled) setStatus(result)
        })
        .catch(() => {
          /* 현황을 못 받아도 시세 화면은 그대로 둔다. */
        })
    }
    load()
    const timer = setInterval(load, 60_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  const latestTradeDate = status?.latest_trade_date ?? null

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
        : fetchStocks({ sort, market: market === 'ALL' ? null : market, limit: LIST_LIMIT })

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
    // latestTradeDate 가 바뀌면 새 확정 종가가 들어온 것이다. 목록을 다시 받는다.
  }, [sort, market, keyword, latestTradeDate])

  // 화면에 떠 있는 종목만 현재가를 받는다. 선택한 종목은 목록 밖일 수 있으니 같이 넣는다.
  const watchedSymbols = useMemo(() => {
    const symbols = stocks.map((s) => s.symbol)
    if (selected && !symbols.includes(selected)) symbols.push(selected)
    return symbols
  }, [stocks, selected])

  const livePrices = useLivePrices(watchedSymbols)

  return (
    <div>
      <header className="mb-6">
        <div className="flex flex-wrap items-center gap-3">
          <MarketBadge market={livePrices.market} error={livePrices.error} realtime={livePrices.realtime} />
        </div>
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
            <Segmented
              size="md"
              label="정렬 기준"
              options={SORT_OPTIONS}
              value={sort}
              onChange={setSort}
            />
            <Segmented
              size="md"
              label="시장"
              options={MARKET_OPTIONS}
              value={market}
              onChange={setMarket}
            />
          </>
        )}

        {loading && <Loading label="불러오는 중…" />}
      </div>

      {error && (
        <ErrorBox tone="block" className="mb-4">
          {error}
        </ErrorBox>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
        <StockTable
          stocks={stocks}
          live={livePrices.bySymbol}
          selectedSymbol={selected}
          onSelect={setSelected}
        />
        <aside>
          {selected && (
            <StockDetailPanel
              symbol={selected}
              live={livePrices.bySymbol.get(selected)}
              market={livePrices.market}
            />
          )}
        </aside>
      </div>

      {status && (
        <footer className="mt-8 border-t border-neutral-800 pt-4 text-xs text-neutral-500">
          <p>출처: {status.source}</p>
          <p className="mt-1">{status.note}</p>
          <p className="mt-1">
            보유 기간 {status.oldest_trade_date} ~ {status.latest_trade_date} ·{' '}
            {status.trading_days} 거래일 · {status.total_rows.toLocaleString()} 행
          </p>
          <p className="mt-1">{describeCollection(status.collection)}</p>
        </footer>
      )}
    </div>
  )
}
