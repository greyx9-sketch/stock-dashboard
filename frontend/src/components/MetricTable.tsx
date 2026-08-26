import type { ScreenRow } from '../lib/api'
import { formatBigWon } from '../lib/format'
import { DataTable, type Column } from './ui/DataTable'

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

function cell(value: string | null, suffix = ''): string {
  return value === null ? '—' : `${value}${suffix}`
}

export function MetricTable({ rows, highlight, onPick, sort, desc, onSort }: Props) {
  const columns: Column<ScreenRow>[] = [
    {
      key: 'name',
      header: '종목',
      render: (row) => (
        <>
          <span className="text-neutral-200">{row.name}</span>
          <span className="tabular ml-1 text-neutral-600">{row.symbol}</span>
          {row.symbol === highlight && (
            <span className="ml-1 rounded bg-neutral-700 px-1 text-xs text-neutral-200">
              이 종목
            </span>
          )}
        </>
      ),
    },
    num('per', 'PER', (row) => cell(row.per), 'text-neutral-200'),
    num('pbr', 'PBR', (row) => cell(row.pbr), 'text-neutral-200'),
    num('roe', 'ROE', (row) => cell(row.roe, '%')),
    num('dividend_yield', '배당', (row) => cell(row.dividend_yield, '%')),
    num('revenue_growth', '매출증가', (row) => cell(row.revenue_growth, '%')),
    num('market_cap', '시총', (row) => formatBigWon(row.market_cap), 'text-neutral-400'),
  ]

  return (
    <DataTable
      variant="embedded"
      dense
      caption="종목별 밸류에이션 지표 비교"
      rows={rows}
      columns={columns}
      rowKey={(row) => row.symbol}
      selectedKey={highlight ?? null}
      onSelect={onPick}
      // 7 열이라 좁은 화면에서는 눌러 담기지 않고 옆으로 넘긴다. 첫 열(종목)은 붙잡아
      // 둬야 가로로 밀었을 때 어느 회사의 숫자인지 알 수 있다.
      minWidth="min-w-[520px]"
      stickyFirst
      sort={sort}
      desc={desc}
      onSort={onSort}
      empty="보여줄 종목이 없습니다."
    />
  )
}

/** 오른쪽 정렬 + 고정폭 숫자 열. 여섯 개가 같은 모양이라 한 줄로 줄인다. */
function num(
  key: string,
  header: string,
  render: (row: ScreenRow) => string,
  tone = 'text-neutral-300',
): Column<ScreenRow> {
  return {
    key,
    header,
    align: 'right',
    sortable: true,
    cellClassName: `tabular ${tone}`,
    render,
  }
}
