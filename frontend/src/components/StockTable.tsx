import type { LiveQuote, Quote } from '../lib/api'
import {
  changeColor,
  formatBigWon,
  formatRate,
  formatVolume,
  formatWon,
} from '../lib/format'

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
  if (stocks.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 p-8 text-center text-sm text-neutral-500">
        조건에 맞는 종목이 없습니다.
      </div>
    )
  }

  // 숫자 칸은 줄바꿈되면 표가 흔들려 읽기 어렵다. 대신 좁으면 가로 스크롤로 넘긴다.
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-800">
      <table className="w-full min-w-[720px] text-sm whitespace-nowrap">
        <thead className="bg-neutral-900 text-xs text-neutral-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium">종목</th>
            <th className="px-3 py-2 text-right font-medium">현재가</th>
            <th className="px-3 py-2 text-right font-medium">등락률</th>
            <th className="px-3 py-2 text-right font-medium">
              확정 종가
              <div className="font-normal text-neutral-600">
                {stocks[0]?.trade_date ?? ''}
              </div>
            </th>
            <th className="px-3 py-2 text-right font-medium">거래량</th>
            <th className="px-3 py-2 text-right font-medium">거래대금</th>
            <th className="px-3 py-2 text-right font-medium">시가총액</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-800/70">
          {stocks.map((stock) => {
            const selected = stock.symbol === selectedSymbol
            const quote = live.get(stock.symbol)
            return (
              <tr
                key={stock.symbol}
                onClick={() => onSelect(stock.symbol)}
                className={`cursor-pointer transition-colors ${
                  selected ? 'bg-neutral-800/80' : 'hover:bg-neutral-900/70'
                }`}
              >
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] ${
                        MARKET_STYLE[stock.market] ?? MARKET_STYLE.KONEX
                      }`}
                    >
                      {stock.market}
                    </span>
                    <span className="font-medium">{stock.name}</span>
                    <span className="tabular text-xs text-neutral-500">{stock.symbol}</span>
                  </div>
                </td>

                {/* 현재가는 아직 못 받았을 수 있다. 그때 확정 종가를 슬쩍 끼워 넣으면
                    다른 시점의 숫자를 현재가로 착각하게 된다. 비워 두는 편이 정직하다. */}
                <td className="tabular px-3 py-2 text-right">
                  {quote ? (
                    formatWon(Number(quote.last_price))
                  ) : (
                    <span className="text-neutral-600">—</span>
                  )}
                </td>
                <td
                  className={`tabular px-3 py-2 text-right ${
                    quote?.change_rate ? changeColor(quote.change_rate) : 'text-neutral-600'
                  }`}
                >
                  {quote?.change_rate ? formatRate(quote.change_rate) : '—'}
                </td>

                <td className="tabular px-3 py-2 text-right text-neutral-300">
                  {formatWon(stock.close)}
                  <span className={`ml-2 text-xs ${changeColor(stock.change_rate)}`}>
                    {formatRate(stock.change_rate)}
                  </span>
                </td>

                <td className="tabular px-3 py-2 text-right text-neutral-400">
                  {formatVolume(stock.volume)}
                </td>
                <td className="tabular px-3 py-2 text-right text-neutral-400">
                  {formatBigWon(stock.trade_value)}
                </td>
                <td className="tabular px-3 py-2 text-right text-neutral-400">
                  {formatBigWon(stock.market_cap)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
