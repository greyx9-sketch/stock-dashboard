import { useMemo, useState } from 'react'
import type { LiveQuote, UsListItem, WatchItem } from '../lib/api'
import { move, refresh, toggle, useWatchlist } from '../lib/watchlistStore'
import { useLivePrices } from '../lib/useLivePrices'
import {
  changeColor,
  formatChange,
  formatRate,
  formatShortDate,
  formatUsdPrice,
  formatWon,
} from '../lib/format'
import { MarketBadge } from '../components/MarketBadge'
import { StockDetailPanel } from '../components/StockDetailPanel'
import { UsDetailPanel } from '../components/UsDetailPanel'

// 관심종목 탭. 기획서 5.1 의 관심종목 그리드다.
//
// 국내와 미국을 한 표에 섞어 보여준다. 그래서 현재가를 두 번 받아 온다 — 국내 종목은
// 국내 장 시간에, 미국 종목은 미국 장 시간에 맞춰 갱신되어야 하기 때문이다. 한 번에
// 묶으면 한쪽 장이 열려 있는 동안 다른 쪽이 30초 간격으로 느려진다.
//
// **거래량은 넣지 않았다.** 토스 현재가 응답에 거래량이 없고, KRX 확정 거래량은 하루
// 늦은 값이다. 국내만 하루 전 거래량을 보여주면 미국 열은 비게 되고, 사용자는 어느
// 시점의 값인지 알 수 없다. 없는 것보다 나쁘다.

const NUMBER_COL = 'tabular px-2 py-1.5 text-right'

export function Watchlist() {
  const { items, loading, error, loaded } = useWatchlist()
  const [selected, setSelected] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [addError, setAddError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const krSymbols = useMemo(
    () => items.filter((i) => i.market === 'KR').map((i) => i.symbol),
    [items],
  )
  const usSymbols = useMemo(
    () => items.filter((i) => i.market === 'US').map((i) => i.symbol),
    [items],
  )

  const kr = useLivePrices(krSymbols, 'KR')
  const us = useLivePrices(usSymbols, 'US')

  const liveOf = (item: WatchItem): LiveQuote | undefined =>
    item.market === 'KR' ? kr.bySymbol.get(item.symbol) : us.bySymbol.get(item.symbol)

  const selectedItem = items.find((i) => i.symbol === selected) ?? null

  const onAdd = (event: React.FormEvent) => {
    event.preventDefault()
    const symbol = input.trim()
    if (!symbol || adding) return
    setAdding(true)
    setAddError(null)
    toggle(symbol)
      .then(() => setInput(''))
      .catch((err: Error) => setAddError(err.message))
      .finally(() => setAdding(false))
  }

  return (
    <div>
      <header className="mb-5">
        <div className="flex flex-wrap items-center gap-3">
          {/* 장 상태를 둘 다 보여준다. 목록에 두 시장이 섞여 있어 하나만 보여주면 오해를 준다.
              어느 쪽 장인지 반드시 적는다 — 배지 두 개가 나란히 있으면 문구만으로는
              구분되지 않는다("장 마감 · 다음 개장 8/18 08:00" 이 둘 다 그럴듯하다). */}
          {krSymbols.length > 0 && (
            <span className="inline-flex items-center gap-1.5">
              <span className="text-xs text-neutral-500">국내</span>
              <MarketBadge market={kr.market} error={kr.error} realtime={kr.realtime} />
            </span>
          )}
          {usSymbols.length > 0 && (
            <span className="inline-flex items-center gap-1.5">
              <span className="text-xs text-neutral-500">미국</span>
              <MarketBadge market={us.market} error={us.error} realtime={us.realtime} />
            </span>
          )}
          {loading && <span className="text-xs text-neutral-500">불러오는 중…</span>}
        </div>
        <p className="mt-1 text-sm text-neutral-400">
          담아 둔 종목 <span className="tabular">{items.length}</span>개 · 종목 상세에서 ★ 를
          눌러 담거나 뺀다
        </p>
      </header>

      <form onSubmit={onAdd} className="mb-4 flex flex-wrap items-center gap-2">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="코드로 담기 (005930 / AAPL)"
          className="w-56 rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm placeholder:text-neutral-600 focus:border-neutral-600 focus:outline-none"
        />
        <button
          type="submit"
          disabled={adding || input.trim() === ''}
          className="rounded-md bg-neutral-100 px-3 py-1.5 text-sm text-neutral-900 transition-colors hover:bg-white disabled:opacity-40"
        >
          담기
        </button>
        {addError && <span className="text-xs text-red-400">{addError}</span>}
      </form>

      {error && (
        <div className="mb-4 rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {loaded && items.length === 0 ? (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-6 text-sm text-neutral-400">
          <p>담아 둔 종목이 없습니다.</p>
          <p className="mt-2 text-neutral-500">
            국내·미국 탭에서 종목을 열고 이름 옆의 <span className="text-amber-400">☆</span> 를
            누르면 여기 모입니다. 위의 입력창에 코드를 넣어 바로 담을 수도 있습니다.
          </p>
          <p className="mt-2 text-neutral-500">
            목록은 서버에 저장되므로 다른 기기에서 열어도 그대로 보입니다.
          </p>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_420px]">
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full text-sm">
              <thead className="bg-neutral-900/60 text-xs text-neutral-500">
                <tr>
                  <th className="px-2 py-2 text-left font-normal">종목</th>
                  <th className="px-2 py-2 text-right font-normal">현재가</th>
                  <th className="px-2 py-2 text-right font-normal">등락률</th>
                  <th className="px-2 py-2 text-right font-normal">기준</th>
                  <th className="px-2 py-2 text-right font-normal">순서</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800">
                {items.map((item, index) => (
                  <Row
                    key={item.symbol}
                    item={item}
                    live={liveOf(item)}
                    selected={item.symbol === selected}
                    isFirst={index === 0}
                    isLast={index === items.length - 1}
                    onSelect={() => setSelected(item.symbol)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <aside>
            {selectedItem === null ? (
              <p className="text-sm text-neutral-500">종목을 누르면 상세가 여기 나옵니다.</p>
            ) : selectedItem.market === 'KR' ? (
              <StockDetailPanel
                symbol={selectedItem.symbol}
                live={kr.bySymbol.get(selectedItem.symbol)}
                market={kr.market}
              />
            ) : (
              <UsDetailPanel
                symbol={selectedItem.symbol}
                listItem={syntheticListItem(selectedItem, us.bySymbol.get(selectedItem.symbol))}
                live={us.bySymbol.get(selectedItem.symbol)}
                market={us.market}
              />
            )}
          </aside>
        </div>
      )}
    </div>
  )
}

type RowProps = {
  item: WatchItem
  live: LiveQuote | undefined
  selected: boolean
  isFirst: boolean
  isLast: boolean
  onSelect: () => void
}

function Row({ item, live, selected, isFirst, isLast, onSelect }: RowProps) {
  const change = computeChange(item, live)

  return (
    <tr
      onClick={onSelect}
      className={`cursor-pointer transition-colors ${
        selected ? 'bg-neutral-800/70' : 'hover:bg-neutral-900/60'
      }`}
    >
      <td className="px-2 py-1.5">
        <div className="flex items-baseline gap-1.5">
          <span className="text-[10px] text-neutral-500">
            {item.market === 'KR' ? '국내' : '미국'}
          </span>
          <span>{item.name}</span>
          <span className="tabular text-xs text-neutral-500">{item.symbol}</span>
        </div>
      </td>
      <td className={NUMBER_COL}>{change.price ?? '—'}</td>
      <td className={`${NUMBER_COL} ${change.rate ? changeColor(change.rate) : 'text-neutral-500'}`}>
        {change.rate === null ? (
          '—'
        ) : (
          <>
            {formatRate(change.rate)}
            {change.amount && (
              <span className="ml-1 text-xs text-neutral-500">{change.amount}</span>
            )}
          </>
        )}
      </td>
      {/* 기준일을 항목마다 적는다. 국내는 KRX 확정 종가(하루 늦다), 미국은 직전 일봉이라
          같은 표 안에서 기준 시점이 다르다. */}
      <td className="px-2 py-1.5 text-right text-[11px] text-neutral-600">
        {item.base_date ? formatShortDate(item.base_date) : '—'}
      </td>
      <td className="px-2 py-1.5 text-right whitespace-nowrap">
        {/* 행 선택과 겹치지 않게 클릭을 여기서 멈춘다. */}
        <span onClick={(event) => event.stopPropagation()}>
          <IconButton label="위로" disabled={isFirst} onClick={() => void move(item.symbol, 'up')}>
            ↑
          </IconButton>
          <IconButton
            label="아래로"
            disabled={isLast}
            onClick={() => void move(item.symbol, 'down')}
          >
            ↓
          </IconButton>
          <IconButton
            label="관심종목에서 빼기"
            onClick={() =>
              void toggle(item.symbol).catch(() => {
                // 실패해도 목록을 서버 기준으로 되돌린다 — 지워진 것처럼 보이면 안 된다.
                void refresh()
              })
            }
          >
            ✕
          </IconButton>
        </span>
      </td>
    </tr>
  )
}

function IconButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string
  disabled?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="rounded px-1.5 py-0.5 text-xs text-neutral-500 transition-colors hover:bg-neutral-800 hover:text-neutral-200 disabled:opacity-25 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  )
}

/**
 * 현재가·등락률·전일비를 화면에 쓸 문자열로 만든다.
 *
 * 등락률은 서버가 준 기준가와 **폴러가 준 최신 현재가**로 직접 계산한다. 기준가는 하루에
 * 한 번만 바뀌고 현재가는 5초마다 바뀌므로, 서버가 계산해 준 값을 그대로 쓰면 현재가만
 * 움직이고 등락률은 멈춰 있는 화면이 된다(미국 목록에서 겪은 것과 같은 문제다).
 */
function computeChange(
  item: WatchItem,
  live: LiveQuote | undefined,
): { price: string | null; rate: string | null; amount: string | null } {
  if (!live) return { price: null, rate: null, amount: null }

  const last = Number(live.last_price)
  const base = item.base_price === null ? NaN : Number(item.base_price)
  const won = item.market === 'KR'
  const price = won ? `${formatWon(last)}` : formatUsdPrice(last)

  if (!Number.isFinite(base) || base === 0 || !Number.isFinite(last)) {
    return { price, rate: null, amount: null }
  }

  const diff = last - base
  return {
    price,
    rate: ((diff / base) * 100).toFixed(2),
    // 전일비 금액. 국내는 원 단위 정수, 미국은 센트까지 본다.
    amount: won ? formatChange(diff) : `${diff > 0 ? '+' : ''}${diff.toFixed(2)}`,
  }
}

/**
 * 미국 상세 패널이 기대하는 목록 항목을 관심종목에서 만들어 준다.
 *
 * 그 패널은 원래 미국 탭의 랭킹 목록과 함께 쓰이도록 만들어져 기준가를 목록 항목에서
 * 받는다. 관심종목에는 랭킹이 없으므로 서버가 준 기준가로 같은 모양을 채운다.
 * 이렇게 하면 패널 쪽을 고치지 않아도 등락률이 제대로 나온다.
 */
function syntheticListItem(item: WatchItem, live: LiveQuote | undefined): UsListItem | undefined {
  if (item.base_price === null) return undefined
  return {
    symbol: item.symbol,
    name: item.name,
    english_name: null,
    market: null,
    // 관심종목은 ETF 인지 주식인지 모른다. null 이면 패널이 SEC 조회를 시도한다 —
    // ETF 라면 조회가 비고, 그 이유는 패널이 화면에 적는다.
    security_type: null,
    last_price: live?.last_price ?? item.base_price,
    base_price: item.base_price,
    change: '0',
    change_rate: '0',
    trading_volume: 0,
    trading_amount: 0,
    currency: 'USD',
  }
}
