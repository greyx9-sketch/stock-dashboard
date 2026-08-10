import type { Quote } from '../lib/api'
import {
  changeColor,
  formatBigWon,
  formatChange,
  formatRate,
  formatVolume,
  formatWon,
} from '../lib/format'

type Props = {
  stocks: Quote[]
  selectedSymbol: string | null
  onSelect: (symbol: string) => void
}

const MARKET_STYLE: Record<string, string> = {
  KOSPI: 'bg-sky-500/15 text-sky-300',
  KOSDAQ: 'bg-amber-500/15 text-amber-300',
  KONEX: 'bg-neutral-500/15 text-neutral-300',
}

export function StockTable({ stocks, selectedSymbol, onSelect }: Props) {
  if (stocks.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 p-8 text-center text-sm text-neutral-500">
        조건에 맞는 종목이 없습니다.
      </div>
    )
  }

  return (
    // 숫자 칸은 줄바꿈되면 표가 흔들려 읽기 어렵다. 대신 좁으면 가로 스크롤로 넘긴다.
    <div className="overflow-x-auto rounded-lg border border-neutral-800">
      <table className="w-full min-w-[720px] text-sm whitespace-nowrap">
        <thead className="bg-neutral-900 text-xs text-neutral-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium">종목</th>
            <th className="px-3 py-2 text-right font-medium">종가</th>
            <th className="px-3 py-2 text-right font-medium">전일대비</th>
            <th className="px-3 py-2 text-right font-medium">등락률</th>
            <th className="px-3 py-2 text-right font-medium">거래량</th>
            <th className="px-3 py-2 text-right font-medium">거래대금</th>
            <th className="px-3 py-2 text-right font-medium">시가총액</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-800/70">
          {stocks.map((stock) => {
            const selected = stock.symbol === selectedSymbol
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
                <td className="tabular px-3 py-2 text-right">{formatWon(stock.close)}</td>
                <td className={`tabular px-3 py-2 text-right ${changeColor(stock.change)}`}>
                  {formatChange(stock.change)}
                </td>
                <td className={`tabular px-3 py-2 text-right ${changeColor(stock.change_rate)}`}>
                  {formatRate(stock.change_rate)}
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
