import type { LiveQuote, UsListItem } from '../lib/api'
import { changeColor, formatBigWon, formatRate, formatUsdPrice, formatVolume } from '../lib/format'
import { usChangeRate, usLastPrice } from '../lib/usRate'

// 미국 종목 목록. 국내와 표를 나눈 이유는 담기는 값이 다르기 때문이다 —
// 미국에는 KRX 확정 종가 같은 별도 기준가 소스가 없어서 그 열이 없고, 대신 ETF 구분이 있다.

type Props = {
  stocks: UsListItem[]
  live: Map<string, LiveQuote>
  selectedSymbol: string | null
  onSelect: (symbol: string) => void
}

const TYPE_STYLE: Record<string, string> = {
  STOCK: 'bg-sky-500/15 text-sky-300',
  ETF: 'bg-violet-500/15 text-violet-300',
  DEPOSITARY_RECEIPT: 'bg-amber-500/15 text-amber-300',
}

const TYPE_LABEL: Record<string, string> = {
  STOCK: '주식',
  ETF: 'ETF',
  DEPOSITARY_RECEIPT: 'DR',
}

export function UsTable({ stocks, live, selectedSymbol, onSelect }: Props) {
  if (stocks.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 p-8 text-center text-sm text-neutral-500">
        조건에 맞는 종목이 없습니다.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-800">
      <table className="w-full min-w-[640px] text-sm whitespace-nowrap">
        <thead className="bg-neutral-900 text-xs text-neutral-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium">종목</th>
            <th className="px-3 py-2 text-right font-medium">현재가</th>
            <th className="px-3 py-2 text-right font-medium">등락률</th>
            <th className="px-3 py-2 text-right font-medium">거래량</th>
            <th className="px-3 py-2 text-right font-medium">거래대금</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-800/70">
          {stocks.map((stock) => {
            const selected = stock.symbol === selectedSymbol
            // 현재가는 폴러(5초), 기준가는 랭킹(60초)에서 온다. 등락률을 다시 계산해
            // 현재가만 움직이고 등락률은 멈춰 있는 화면이 되지 않게 한다.
            const quote = live.get(stock.symbol)
            const price = usLastPrice(stock, quote)
            const rate = usChangeRate(stock, quote)
            const type = stock.security_type ?? 'STOCK'

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
                        TYPE_STYLE[type] ?? TYPE_STYLE.STOCK
                      }`}
                    >
                      {TYPE_LABEL[type] ?? type}
                    </span>
                    <span className="font-medium">{stock.name}</span>
                    <span className="tabular text-xs text-neutral-500">{stock.symbol}</span>
                  </div>
                </td>
                <td className="tabular px-3 py-2 text-right">
                  {price === undefined ? (
                    <span className="text-neutral-600">—</span>
                  ) : (
                    formatUsdPrice(price)
                  )}
                </td>
                <td
                  className={`tabular px-3 py-2 text-right ${
                    rate === null ? 'text-neutral-600' : changeColor(rate)
                  }`}
                >
                  {rate === null ? '—' : formatRate(rate)}
                </td>
                <td className="tabular px-3 py-2 text-right text-neutral-400">
                  {formatVolume(stock.trading_volume)}
                </td>
                {/* 거래대금은 토스가 원화로 환산해 준다. 달러가 아니다. */}
                <td className="tabular px-3 py-2 text-right text-neutral-400">
                  {formatBigWon(stock.trading_amount)}원
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
