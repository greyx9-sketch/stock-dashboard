import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchStatus, fetchStocks, searchStocks } from '../lib/api'
import type { DataStatus, MarketFilter, Quote, SortKey } from '../lib/api'
import type { Section } from '../lib/useRoute'
import { useLivePrices } from '../lib/useLivePrices'
import { formatTimestamp } from '../lib/format'
import { StockTable } from '../components/StockTable'
import { StockDetailPanel } from '../components/StockDetailPanel'
import { MarketBadge } from '../components/MarketBadge'
import { Segmented } from '../components/ui/Segmented'
import { SplitView } from '../components/ui/SplitView'
import { Announce, ErrorBox, Loading } from '../components/ui/Status'

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

type Props = {
  /** 지금 열려 있는 종목. 주소가 들고 있다(`lib/useRoute`). */
  symbol: string | null
  section: Section
  onSelect: (symbol: string | null) => void
  onSection: (section: Section) => void
}

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

export function KrMarket({ symbol, section, onSelect, onSection }: Props) {
  const [status, setStatus] = useState<DataStatus | null>(null)
  const [stocks, setStocks] = useState<Quote[]>([])
  const [sort, setSort] = useState<SortKey>('market_cap')
  const [market, setMarket] = useState<MarketChoice>('ALL')
  const [keyword, setKeyword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // 목록을 받은 뒤 "지금 뭐가 열려 있나"를 봐야 하는데, 그것을 의존성에 넣으면 종목을
  // 누를 때마다 목록을 다시 받게 된다. 값만 따로 들고 본다.
  const selectedRef = useRef(symbol)
  selectedRef.current = symbol

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

          const current = selectedRef.current
          const inList = current !== null && result.some((s) => s.symbol === current)
          // 처음 들어왔거나(주소에 종목이 없다), 검색으로 목록이 통째로 바뀌었는데 그 안에
          // 없으면 첫 종목을 연다.
          //
          // 검색이 아닐 때는 목록 밖 종목이어도 그대로 둔다 — 주소로 링크를 받고 들어온
          // 종목이 "거래대금 상위 50위 밖"이라는 이유로 다른 회사로 튕기면 안 된다.
          if (current === null || (trimmed !== '' && !inList)) {
            onSelect(result[0]?.symbol ?? null)
          }
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
  }, [sort, market, keyword, latestTradeDate, onSelect])

  // 화면에 떠 있는 종목만 현재가를 받는다. 선택한 종목은 목록 밖일 수 있으니 같이 넣는다.
  const watchedSymbols = useMemo(() => {
    const symbols = stocks.map((s) => s.symbol)
    if (symbol && !symbols.includes(symbol)) symbols.push(symbol)
    return symbols
  }, [stocks, symbol])

  const livePrices = useLivePrices(watchedSymbols)
  const selectedRow = stocks.find((s) => s.symbol === symbol)

  // 좁은 화면에서 목록·상세 중 무엇을 보여 줄지. 주소에 종목이 적혀 있으면(링크를
  // 받고 들어온 경우) 상세로 시작하고, 그렇지 않으면 목록부터 보여준다.
  const [view, setView] = useState<'list' | 'detail'>(symbol ? 'detail' : 'list')

  // 목록이 처음 뜨면서 첫 종목을 자동으로 여는 것은 "눌렀다"가 아니다. 그것까지
  // 상세로 치면 휴대폰에서 앱을 열자마자 상세로 튕긴다. 사용자가 누른 길만 이것을 쓴다.
  const open = (next: string | null) => {
    onSelect(next)
    if (next) setView('detail')
  }

  // 목록이 바뀜 것을 소리로 알린다. 받는 중에는 비워 둔다 — 중간에 한 번 더
  // 말하게 하지 않고 결과만 한 번 말하게 하려는 것이다.
  const trimmedKeyword = keyword.trim()
  const listSummary = loading
    ? ''
    : trimmedKeyword !== ''
      ? `“${trimmedKeyword}” 검색 결과 ${stocks.length}건`
      : `${SORT_OPTIONS.find((o) => o.value === sort)?.label} 순 · ` +
        `${MARKET_OPTIONS.find((o) => o.value === market)?.label} · ${stocks.length}종목`

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

      {/* 좁은 화면에서 상세를 보는 중이면 도구줄을 감춘다. 검색·정렬·시장은 목록에 따라붙는
          것이라, 상세만 보이는 화면 위에 남아 있으면 한 화면분을 그냥 잡아먹는다. */}
      <div
        className={`mb-4 flex-wrap items-center gap-2 ${
          view === 'detail' ? 'hidden lg:flex' : 'flex'
        }`}
      >
        <input
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="종목명 또는 코드 검색"
          className="w-56 rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm placeholder:text-neutral-600 focus:border-neutral-600"
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

      <Announce>{listSummary}</Announce>

      {error && (
        <ErrorBox tone="block" className="mb-4">
          {error}
        </ErrorBox>
      )}

      {/* 상세 기둥을 420px 에서 넓혔다. 동종업계 표가 520px 이라 예전 폭에서는 매출 열이
          늘 화면 밖으로 잘려 나갔다 — 있는데 안 보이는 상태였다.
          좁은 화면에서 목록·상세를 갈라 보여주는 것은 `SplitView` 가 맡는다. */}
      <SplitView
        // 종목이 없으면 보여 줄 상세도 없다. 뒤로가기로 주소에서 종목이 빠졌을 때
        // 빈 상세가 남아 있지 않게 한다.
        view={symbol ? view : 'list'}
        onBack={() => setView('list')}
        backLabel="종목 목록으로"
        className="gap-6 lg:grid-cols-[minmax(0,1fr)_480px] xl:grid-cols-[minmax(0,1fr)_560px]"
        list={
          <StockTable
            stocks={stocks}
            live={livePrices.bySymbol}
            selectedSymbol={symbol}
            onSelect={open}
          />
        }
        detail={
          symbol && (
            <StockDetailPanel
              symbol={symbol}
              name={selectedRow?.name}
              live={livePrices.bySymbol.get(symbol)}
              market={livePrices.market}
              section={section}
              onSection={onSection}
            />
          )
        }
      />

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
