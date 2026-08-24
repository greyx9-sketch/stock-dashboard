import type { ScreenRow } from '../lib/api'
import { formatBigWon } from '../lib/format'

// 지표 표. 스크리너와 동종업계 비교가 **같은 표**를 쓴다.
//
// 같은 숫자를 두 곳에서 다르게 그리면, 같은 종목의 PER 이 화면마다 달라 보이는 일이
// 생긴다. 계산이 한 곳(백엔드 `screen_rows`)에서 나오듯 그리는 것도 한 곳에서 한다.
//
// 색: PER·PBR 은 낮을수록, ROE·배당·성장은 높을수록 좋다고 흔히 읽지만 **색으로
// 좋고 나쁨을 칠하지 않는다.** 업종마다 적정 수준이 달라서(은행 PBR 0.5 는 정상,
// 바이오 PBR 0.5 는 이상 신호) 색을 칠하면 판단을 대신하게 된다. 이 사이트는 자료를
// 보여주고 판단은 사람이 한다.

type Props = {
  rows: ScreenRow[]
  /** 이 종목 줄을 도드라지게 한다 (동종업계 비교에서 '나'를 표시). */
  highlight?: string
  onPick?: (symbol: string) => void
  /** 정렬 가능한 표일 때. 없으면 머리글이 그냥 글자다. */
  sort?: string
  desc?: boolean
  onSort?: (key: string) => void
}

const COLUMNS: { key: string; label: string; sortable: boolean }[] = [
  { key: 'name', label: '종목', sortable: false },
  { key: 'per', label: 'PER', sortable: true },
  { key: 'pbr', label: 'PBR', sortable: true },
  { key: 'roe', label: 'ROE', sortable: true },
  { key: 'dividend_yield', label: '배당', sortable: true },
  { key: 'revenue_growth', label: '매출증가', sortable: true },
  { key: 'market_cap', label: '시총', sortable: true },
]

function cell(value: string | null, suffix = ''): string {
  return value === null ? '—' : `${value}${suffix}`
}

export function MetricTable({ rows, highlight, onPick, sort, desc, onSort }: Props) {
  if (rows.length === 0) {
    return <p className="px-3 py-4 text-xs text-neutral-500">보여줄 종목이 없습니다.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-neutral-800 text-neutral-500">
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                onClick={col.sortable && onSort ? () => onSort(col.key) : undefined}
                className={`px-2 py-1.5 font-normal ${
                  col.key === 'name' ? 'text-left' : 'text-right'
                } ${col.sortable && onSort ? 'cursor-pointer hover:text-neutral-300' : ''}`}
              >
                {col.label}
                {sort === col.key && <span className="ml-0.5">{desc ? '↓' : '↑'}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.symbol}
              onClick={onPick ? () => onPick(row.symbol) : undefined}
              className={`border-b border-neutral-900 transition-colors ${
                onPick ? 'cursor-pointer hover:bg-neutral-800/50' : ''
              } ${row.symbol === highlight ? 'bg-neutral-800/60' : ''}`}
            >
              <td className="px-2 py-1.5">
                <span className="text-neutral-200">{row.name}</span>
                <span className="tabular ml-1 text-neutral-600">{row.symbol}</span>
                {row.symbol === highlight && (
                  <span className="ml-1 rounded bg-neutral-700 px-1 text-[10px] text-neutral-200">
                    이 종목
                  </span>
                )}
              </td>
              <td className="tabular px-2 py-1.5 text-right text-neutral-200">{cell(row.per)}</td>
              <td className="tabular px-2 py-1.5 text-right text-neutral-200">{cell(row.pbr)}</td>
              <td className="tabular px-2 py-1.5 text-right text-neutral-300">
                {cell(row.roe, '%')}
              </td>
              <td className="tabular px-2 py-1.5 text-right text-neutral-300">
                {cell(row.dividend_yield, '%')}
              </td>
              <td className="tabular px-2 py-1.5 text-right text-neutral-300">
                {cell(row.revenue_growth, '%')}
              </td>
              <td className="tabular px-2 py-1.5 text-right text-neutral-400">
                {formatBigWon(row.market_cap)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
