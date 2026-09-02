import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchUsList, searchUsStocks, type UsSort } from '../lib/api'
import type { UsListItem } from '../lib/api'
import type { Section } from '../lib/useRoute'
import { useLivePrices } from '../lib/useLivePrices'
import { UsTable } from '../components/UsTable'
import { UsDetailPanel } from '../components/UsDetailPanel'
import { MarketBadge } from '../components/MarketBadge'
import { Announce, ErrorBox } from '../components/ui/Status'
import { SplitView } from '../components/ui/SplitView'
import { Segmented } from '../components/ui/Segmented'

// 미국 시장 화면.
//
// 목록은 토스증권 거래대금 상위 랭킹에서 온다. 국내처럼 전 종목 DB 가 없기 때문인데,
// 어차피 미국 상장사는 1만 곳이 넘어서 전부 나열하는 것은 화면에도 의미가 없다.
// 특정 종목을 보려면 검색을 쓴다 — 검색은 SEC 티커 목록(10,387건) 전체를 대상으로 한다.

const LIST_LIMIT = 50

type Props = {
  /** 지금 열려 있는 종목. 주소가 들고 있다(`lib/useRoute`). */
  symbol: string | null
  section: Section
  onSelect: (symbol: string | null) => void
  onSection: (section: Section) => void
}

// 국내(`KrMarket`)의 정렬 선택과 같은 자리·같은 부품이다. 담기는 것만 다르다 —
// 시가총액 순이 없고(토스 랭킹에 그 종류가 없다) 대신 등락률이 상승·하락으로 갈린다.
const SORT_OPTIONS = [
  { value: 'trade_value', label: '거래대금' },
  { value: 'volume', label: '거래량' },
  { value: 'gainers', label: '상승률' },
  { value: 'losers', label: '하락률' },
] as const satisfies readonly { value: UsSort; label: string }[]

export function UsMarket({ symbol, section, onSelect, onSection }: Props) {
  const [stocks, setStocks] = useState<UsListItem[]>([])
  const [sort, setSort] = useState<UsSort>('trade_value')
  const [keyword, setKeyword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // 국내 화면과 같은 이유 — 목록을 받은 뒤 열려 있는 종목을 봐야 하지만, 그것을
  // 의존성에 넣으면 종목을 누를 때마다 목록을 다시 받는다.
  const selectedRef = useRef(symbol)
  selectedRef.current = symbol

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    const trimmed = keyword.trim()
    const timer = setTimeout(() => {
      // 검색 결과에는 시세가 없다(SEC 목록이라 이름·티커뿐). 목록 모양으로 맞춰 두고
      // 현재가는 폴러가 채우게 한다.
      const request: Promise<UsListItem[]> = trimmed
        ? searchUsStocks(trimmed).then((found) =>
            found.map((company) => ({
              symbol: company.ticker,
              name: company.name,
              english_name: company.name,
              market: null,
              security_type: null,
              last_price: '0',
              base_price: '0',
              change: '0',
              change_rate: '0',
              trading_volume: 0,
              trading_amount: 0,
              currency: 'USD',
            })),
          )
        : fetchUsList(LIST_LIMIT, sort)

      request
        .then((result) => {
          if (cancelled) return
          setStocks(result)

          const current = selectedRef.current
          const inList = current !== null && result.some((s) => s.symbol === current)
          if (current === null || (trimmed !== '' && !inList)) {
            // 거래대금 상위에는 ETF 가 많이 올라오는데, ETF 는 재무·공시가 비어 있어
            // 첫 화면으로는 허전하다. 사업회사가 있으면 그쪽을 먼저 연다.
            const firstStock = result.find((s) => s.security_type === 'STOCK')
            onSelect((firstStock ?? result[0])?.symbol ?? null)
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
  }, [keyword, sort, onSelect])

  const watchedSymbols = useMemo(() => {
    const symbols = stocks.map((s) => s.symbol)
    if (symbol && !symbols.includes(symbol)) symbols.push(symbol)
    return symbols
  }, [stocks, symbol])

  // 미국 화면이므로 미국 장 상태를 본다. 한국 장 시간과 완전히 다르다.
  const livePrices = useLivePrices(watchedSymbols, 'US')
  const selectedItem = stocks.find((s) => s.symbol === symbol)

  // 좁은 화면에서 목록·상세 중 무엇을 보여 줄지. 주소에 종목이 적혀 있으면(링크를
  // 받고 들어온 경우) 상세로 시작하고, 그렇지 않으면 목록부터 보여준다.
  const [view, setView] = useState<'list' | 'detail'>(symbol ? 'detail' : 'list')

  // 목록이 처음 뜨면서 첫 종목을 자동으로 여는 것은 "눌렀다"가 아니다. 그것까지
  // 상세로 치면 휴대폰에서 앱을 열자마자 상세로 튕긴다. 사용자가 누른 길만 이것을 쓴다.
  const open = (next: string | null) => {
    onSelect(next)
    if (next) setView('detail')
  }

  // 국내 화면과 같은 규칙 — 목록이 바뀜 것을 소리로 알린다.
  const trimmedKeyword = keyword.trim()
  const listSummary = loading
    ? ''
    : trimmedKeyword !== ''
      ? `“${trimmedKeyword}” 검색 결과 ${stocks.length}건`
      : `${SORT_OPTIONS.find((o) => o.value === sort)?.label} 상위 ${stocks.length}종목`

  return (
    <div>
      <header className="mb-6">
        <div className="flex flex-wrap items-center gap-3">
          <MarketBadge market={livePrices.market} error={livePrices.error} realtime={livePrices.realtime} />
        </div>
        <p className="mt-1 text-sm text-neutral-400">
          {keyword.trim()
            ? 'SEC 등록 기업 검색 결과'
            : `토스증권 ${SORT_OPTIONS.find((o) => o.value === sort)?.label} 상위 · 재무와 공시는 SEC EDGAR`}
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
          placeholder="티커 또는 회사명 검색 (예: AAPL, Apple)"
          className="w-72 rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm placeholder:text-neutral-600 focus:border-neutral-600"
        />
        {/* 검색 중에는 감춘다. 검색 결과는 랭킹이 아니라 SEC 기업 목록이라
            정렬 기준이 걸리지 않는다 — 국내 화면과 같은 규칙이다. */}
        {keyword.trim() === '' && (
          <Segmented
            size="md"
            label="정렬 기준"
            options={SORT_OPTIONS}
            value={sort}
            onChange={(next) => setSort(next as UsSort)}
          />
        )}
        {loading && <span className="text-xs text-neutral-500">불러오는 중…</span>}
      </div>

      <Announce>{listSummary}</Announce>

      {error && (
        <ErrorBox tone="block" className="mb-4">
          {error}
        </ErrorBox>
      )}

      {/* 국내 화면과 같은 짜임 — 넓힌 상세 기둥 · 화면에 붙잡아 두기 · 좁은 화면에서는 둘 중 하나.
          두 화면이 다르게 움직이면 탭을 옮길 때마다 규칙을 다시 익혀야 한다. */}
      <SplitView
        // 종목이 없으면 보여 줄 상세도 없다. 뒤로가기로 주소에서 종목이 빠졌을 때
        // 빈 상세가 남아 있지 않게 한다.
        view={symbol ? view : 'list'}
        onBack={() => setView('list')}
        backLabel="종목 목록으로"
        className="gap-6 lg:grid-cols-[minmax(0,1fr)_480px] xl:grid-cols-[minmax(0,1fr)_560px]"
        list={
          <UsTable
            stocks={stocks}
            live={livePrices.bySymbol}
            selectedSymbol={symbol}
            onSelect={open}
          />
        }
        detail={
          symbol && (
            <UsDetailPanel
              symbol={symbol}
              listItem={selectedItem}
              live={livePrices.bySymbol.get(symbol)}
              market={livePrices.market}
              section={section}
              onSection={onSection}
            />
          )
        }
      />

      <footer className="mt-8 border-t border-neutral-800 pt-4 text-xs text-neutral-500">
        <p>시세: 토스증권 · 재무와 공시: SEC EDGAR (10-K / 10-Q / 8-K)</p>
        <p className="mt-1">
          회계연도는 대부분 걸쳐 있는 달력 연도로 표기한다. 회사가 스스로 부르는 이름과 다를 수
          있으므로(월마트는 2025년 1월 결산을 FY2025 라 부른다) 막대에 마우스를 올려 결산일을
          함께 확인한다.
        </p>
        <p className="mt-1">ETF 는 연차보고서(10-K)를 내지 않아 재무·공시가 비어 있다.</p>
      </footer>
    </div>
  )
}
