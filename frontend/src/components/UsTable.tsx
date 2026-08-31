import type { LiveQuote, UsListItem } from '../lib/api'
import { changeColor, formatBigWon, formatRate, formatUsdPrice, formatVolume } from '../lib/format'
import { usChangeRate, usLastPrice } from '../lib/usRate'
import { DataTable, type Column } from './ui/DataTable'

// 미국 종목 목록. 국내와 열을 나눈 이유는 담기는 값이 다르기 때문이다 —
// 미국에는 KRX 확정 종가 같은 별도 기준가 소스가 없어서 그 열이 없고, 대신 ETF 구분이 있다.
// 표의 골격(키보드 이동·빈 상태·가로 스크롤)은 DataTable 이 국내와 함께 맡는다.

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
  const columns: Column<UsListItem>[] = [
    {
      key: 'name',
      header: '종목',
      render: (stock) => {
        const type = stock.security_type ?? 'STOCK'
        return (
          <div className="flex items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 text-xs ${TYPE_STYLE[type] ?? TYPE_STYLE.STOCK}`}>
              {TYPE_LABEL[type] ?? type}
            </span>
            <span className="font-medium">{stock.name}</span>
            <span className="tabular text-xs text-neutral-500">{stock.symbol}</span>
          </div>
        )
      },
    },
    {
      key: 'price',
      header: '현재가',
      align: 'right',
      cellClassName: 'tabular',
      render: (stock) => {
        const price = usLastPrice(stock, live.get(stock.symbol))
        return price === undefined ? <span className="text-neutral-600">—</span> : formatUsdPrice(price)
      },
    },
    {
      key: 'change',
      header: '등락률',
      align: 'right',
      // 현재가는 폴러(5초), 기준가는 랭킹(60초)에서 온다. 등락률을 다시 계산해
      // 현재가만 움직이고 등락률은 멈춰 있는 화면이 되지 않게 한다.
      cellClassName: (stock) => {
        const rate = usChangeRate(stock, live.get(stock.symbol))
        return `tabular ${rate === null ? 'text-neutral-600' : changeColor(rate)}`
      },
      render: (stock) => {
        const rate = usChangeRate(stock, live.get(stock.symbol))
        return rate === null ? '—' : formatRate(rate)
      },
    },
    {
      key: 'volume',
      header: '거래량',
      align: 'right',
      // 국내 목록과 같은 규칙 — 휴대폰에는 종목·현재가·등락률만 남긴다.
      hideBelow: 'sm',
      cellClassName: 'tabular text-neutral-400',
      render: (stock) => formatVolume(stock.trading_volume),
    },
    {
      key: 'trade_value',
      header: '거래대금',
      align: 'right',
      hideBelow: 'sm',
      cellClassName: 'tabular text-neutral-400',
      // 거래대금은 토스가 원화로 환산해 준다. 달러가 아니다.
      render: (stock) => `${formatBigWon(stock.trading_amount)}원`,
    },
  ]

  return (
    <DataTable
      caption="미국 종목 시세 목록"
      rows={stocks}
      columns={columns}
      rowKey={(stock) => stock.symbol}
      selectedKey={selectedSymbol}
      onSelect={onSelect}
      minWidth="min-w-0 sm:min-w-[640px]"
      empty="조건에 맞는 종목이 없습니다."
    />
  )
}
