import type { LiveQuote, Quote } from '../lib/api'
import {
  changeColor,
  formatBigWon,
  formatRate,
  formatVolume,
  formatWon,
} from '../lib/format'
import { DataTable, type Column } from './ui/DataTable'

type Props = {
  stocks: Quote[]
  live: Map<string, LiveQuote>
  selectedSymbol: string | null
  onSelect: (symbol: string) => void
}

const MARKET_STYLE: Record<string, string> = {
  KOSPI: 'bg-sky-500/15 text-sky-300',
  KOSDAQ: 'bg-amber-500/15 text-amber-300',
  KONEX: 'bg-neutral-500/15 text-neutral-300',
}

export function StockTable({ stocks, live, selectedSymbol, onSelect }: Props) {
  const columns: Column<Quote>[] = [
    {
      key: 'name',
      header: '종목',
      render: (stock) => (
        <div className="flex items-center gap-2">
          <span
            className={`rounded px-1.5 py-0.5 text-xs ${
              MARKET_STYLE[stock.market] ?? MARKET_STYLE.KONEX
            }`}
          >
            {stock.market}
          </span>
          <span className="font-medium">{stock.name}</span>
          {/* 휴대폰에서는 종목코드를 감춘다. 이름으로 이미 구분되고, 여섯 자리가
              더 붙으면 등락률 열이 화면 밖으로 밀려난다. */}
          <span className="tabular hidden text-xs text-neutral-500 sm:inline">{stock.symbol}</span>
        </div>
      ),
    },
    {
      key: 'price',
      header: '현재가',
      align: 'right',
      cellClassName: 'tabular',
      // 현재가는 아직 못 받았을 수 있다. 그때 확정 종가를 슬쩍 끼워 넣으면
      // 다른 시점의 숫자를 현재가로 착각하게 된다. 비워 두는 편이 정직하다.
      render: (stock) => {
        const quote = live.get(stock.symbol)
        return quote ? (
          formatWon(Number(quote.last_price))
        ) : (
          <span className="text-neutral-600">—</span>
        )
      },
    },
    {
      key: 'change',
      header: '등락률',
      align: 'right',
      cellClassName: (stock) => {
        const rate = live.get(stock.symbol)?.change_rate
        return `tabular ${rate ? changeColor(rate) : 'text-neutral-600'}`
      },
      render: (stock) => {
        const rate = live.get(stock.symbol)?.change_rate
        return rate ? formatRate(rate) : '—'
      },
    },
    {
      key: 'close',
      header: '확정 종가',
      subHeader: stocks[0]?.trade_date ?? '',
      align: 'right',
      // 휴대폰에서는 일곱 열을 가로로 미는 것보다 세 열만 남기는 편이 읽힐다.
      // 남기는 셋은 **지금 얼마인가**에 답하는 열이다 — 종목·현재가·등락률.
      hideBelow: 'sm',
      cellClassName: 'tabular text-neutral-300',
      render: (stock) => (
        <>
          {formatWon(stock.close)}
          <span className={`ml-2 text-xs ${changeColor(stock.change_rate)}`}>
            {formatRate(stock.change_rate)}
          </span>
        </>
      ),
    },
    {
      key: 'volume',
      header: '거래량',
      align: 'right',
      hideBelow: 'sm',
      cellClassName: 'tabular text-neutral-400',
      render: (stock) => formatVolume(stock.volume),
    },
    {
      key: 'trade_value',
      header: '거래대금',
      align: 'right',
      hideBelow: 'sm',
      cellClassName: 'tabular text-neutral-400',
      render: (stock) => formatBigWon(stock.trade_value),
    },
    {
      key: 'market_cap',
      header: '시가총액',
      align: 'right',
      hideBelow: 'sm',
      cellClassName: 'tabular text-neutral-400',
      render: (stock) => formatBigWon(stock.market_cap),
    },
  ]

  return (
    <DataTable
      caption="국내 종목 시세 목록"
      rows={stocks}
      columns={columns}
      rowKey={(stock) => stock.symbol}
      selectedKey={selectedSymbol}
      onSelect={onSelect}
      empty="조건에 맞는 종목이 없습니다."
    />
  )
}
