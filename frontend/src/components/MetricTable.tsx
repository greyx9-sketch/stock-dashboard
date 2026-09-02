import type { ScreenRow } from '../lib/api'
import { formatBigWon, formatUsd } from '../lib/format'
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
  /** 시가총액을 어느 통화로 적을지. 미국 스크리너·동종업계가 'USD' 를 준다. */
  currency?: 'KRW' | 'USD'
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

export function MetricTable({ rows, currency = 'KRW', highlight, onPick, sort, desc, onSort }: Props) {
  const columns: Column<ScreenRow>[] = [
    {
      key: 'name',
      header: '종목',
      render: (row) => (
        <>
          <span className="text-neutral-200">{row.name}</span>
          <span className="tabular ml-1 hidden text-neutral-600 sm:inline">{row.symbol}</span>
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
    // 일곱 열은 휴대폰에 안 들어간다. 시총·매출증가를 감추면 지표 네 열이 남아
    // 가로로 밀지 않고도 PER·PBR·ROE·배당을 한 눈에 볼 수 있다.
    num('revenue_growth', '매출증가', (row) => cell(row.revenue_growth, '%'), undefined, 'sm'),
    num(
      'market_cap',
      '시총',
      (row) =>
        row.market_cap === null
          ? '—'
          : currency === 'USD'
            ? formatUsd(row.market_cap)
            : formatBigWon(row.market_cap),
      'text-neutral-400',
      'sm',
    ),
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
      // 520px 이던 것을 460 으로 내렸다. 이 표는 종목 상세의 동종업계 비교로도 쓰이는데
      // 그 기둥이 520 보다 좁아서 매출 열이 늘 잘려 나갔다 — 있는데 안 보이는 상태였다.
      // 기둥을 480 으로 넓히고 표를 460 으로 줄여 양쪽에서 만나게 했다.
      // 그보다 더 좁아지면 눌러 담지 않고 옆으로 넘긴다. 첫 열(종목)은 붙잡아 둬야
      // 가로로 밀었을 때 어느 회사의 숫자인지 알 수 있다.
      minWidth="min-w-0 sm:min-w-[460px]"
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
  hideBelow?: 'sm' | 'md',
): Column<ScreenRow> {
  return {
    key,
    header,
    align: 'right',
    sortable: true,
    hideBelow,
    cellClassName: `tabular ${tone}`,
    render,
  }
}
