import { useRef } from 'react'
import type { ReactNode } from 'react'
import { Card } from './Card'

// 목록 표. 국내·미국·관심종목이 각자 <table> 을 처음부터 다시 쓰고 있었다.
//
// 합치는 진짜 이유는 줄 수가 아니라 **접근성이 세 곳에 각각 빠져 있었다**는 것이다.
// 종목을 고르는 것이 이 앱의 핵심 동작인데 <tr onClick> 이라 키보드로는 아예 닿을 수가
// 없었다. 마우스를 못 쓰는 사람에게는 앱이 열리지 않는 것과 같다.
//
// 한 곳에서 처리하는 것:
//   · 화살표로 행 이동, Enter/Space 로 선택 (roving tabindex — 표 전체가 탭 정지 하나)
//   · <caption> 으로 이 표가 무엇인지 알림
//   · 좁은 화면에서 첫 열 고정 — 가로로 밀어도 어느 종목 줄인지 남는다
//   · 비어 있을 때의 표시

export type Column<T> = {
  key: string
  header: ReactNode
  /** 머리글 아래 작은 줄. 확정 종가의 기준일처럼 열 자체에 붙는 단서. */
  subHeader?: ReactNode
  align?: 'left' | 'right'
  /** 이 열로 정렬할 수 있는가. onSort 가 함께 있어야 실제로 동작한다. */
  sortable?: boolean
  /** 칸에 붙는 추가 클래스. 값에 따라 달라지면 함수로 준다(등락 색 등). */
  cellClassName?: string | ((row: T) => string)
  /**
   * 이 폭보다 좁으면 열을 감춘다. 휴대폰에서 일곱 열을 가로로 미는 것보다,
   * 꼭 봐야 하는 세 열만 남기는 편이 읽힌다. 감출 열은 화면마다 다르므로 여기서 정한다.
   */
  hideBelow?: 'sm' | 'md'
  render: (row: T) => ReactNode
}

type DataTableProps<T> = {
  rows: readonly T[]
  columns: readonly Column<T>[]
  rowKey: (row: T) => string
  /** 스크린리더가 읽을 표 설명. "국내 종목 시세 목록" 처럼. */
  caption: string
  selectedKey?: string | null
  onSelect?: (key: string) => void
  /**
   * 이보다 좁아지면 가로로 스크롤한다. 숫자 칸이 줄바꿈되면 표가 흔들려 못 읽는다.
   * **휴대폰에서는 풀어 준다** — `min-w-0 sm:min-w-[720px]` 처럼 적으면 좁은 화면에서만
   * 가로 밀기가 사라지고, 대신 `hideBelow` 로 감춘 열만큼 표가 좁아진다.
   */
  minWidth?: string
  /** 가로 스크롤 시 첫 열을 붙잡아 둔다. */
  stickyFirst?: boolean
  empty?: ReactNode
  /** card = 테두리를 두른 독립 표 · embedded = 카드 안에 박히는 표 */
  variant?: 'card' | 'embedded'
  /** 열이 많아 자리가 빠듯할 때. 여백과 글자를 한 단 줄인다. */
  dense?: boolean
  /** 정렬 상태. 머리글이 버튼이 되고 aria-sort 가 붙는다. */
  sort?: string
  desc?: boolean
  onSort?: (key: string) => void
}

// Tailwind 는 클래스 이름을 소스에서 글자 그대로 찾는다. `hidden ${bp}:table-cell` 처럼
// 만들면 빌드에 안 들어가므로 표를 미리 적어 둔다.
const HIDE_BELOW: Record<'sm' | 'md', string> = {
  sm: 'hidden sm:table-cell',
  md: 'hidden md:table-cell',
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  caption,
  selectedKey,
  onSelect,
  minWidth = 'min-w-0 sm:min-w-[720px]',
  stickyFirst = false,
  empty = '조건에 맞는 항목이 없습니다.',
  variant = 'card',
  dense = false,
  sort,
  desc,
  onSort,
}: DataTableProps<T>) {
  const bodyRef = useRef<HTMLTableSectionElement>(null)
  // 좌우 12px 이던 것을 10px 로 줄였다. 열이 일곱이라 2px 씩만 줄여도 표 전체가 28px
  // 좁아지는데, 상세 기둥을 넓히면서 목록에 남은 폭이 딱 그만큼 모자랐다.
  // 글자 크기는 건드리지 않는다 — 0단계에서 올려 둔 것이다.
  const pad = dense ? 'px-2 py-1.5' : 'px-2.5 py-2'
  const embedded = variant === 'embedded'

  if (rows.length === 0) {
    return embedded ? (
      <p className="px-3 py-4 text-xs text-neutral-500">{empty}</p>
    ) : (
      <Card bodyClassName="p-8 text-center text-sm text-neutral-500">{empty}</Card>
    )
  }

  // 화살표로 옮긴 행에 실제로 포커스를 준다. 포커스가 따라가지 않으면 스크린리더가
  // 어디로 갔는지 말해 주지 못한다.
  const moveFocus = (from: number, delta: number | 'first' | 'last') => {
    const next =
      delta === 'first'
        ? 0
        : delta === 'last'
          ? rows.length - 1
          : Math.min(Math.max(from + delta, 0), rows.length - 1)
    const target = bodyRef.current?.children[next] as HTMLElement | undefined
    target?.focus()
    onSelect?.(rowKey(rows[next]))
  }

  const handleKey = (event: React.KeyboardEvent, index: number) => {
    const row = rows[index]
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        moveFocus(index, 1)
        break
      case 'ArrowUp':
        event.preventDefault()
        moveFocus(index, -1)
        break
      case 'Home':
        event.preventDefault()
        moveFocus(index, 'first')
        break
      case 'End':
        event.preventDefault()
        moveFocus(index, 'last')
        break
      case 'Enter':
      case ' ':
        event.preventDefault()
        onSelect?.(rowKey(row))
        break
    }
  }

  // 선택된 행이 없으면 첫 행이 탭 정지를 갖는다. 표에 들어오는 문은 항상 하나다.
  const focusIndex = Math.max(
    rows.findIndex((row) => rowKey(row) === selectedKey),
    0,
  )
  const selectable = onSelect !== undefined

  return (
    <div
      className={`overflow-x-auto ${embedded ? '' : 'rounded-lg shadow-edge'}`}
    >
      <table className={`w-full ${minWidth} ${dense ? 'text-xs' : 'text-sm'} whitespace-nowrap`}>
        <caption className="sr-only">{caption}</caption>
        <thead
          className={
            embedded
              ? 'border-b border-neutral-800 text-xs text-neutral-500'
              : 'bg-neutral-900 text-xs text-neutral-400'
          }
        >
          <tr>
            {columns.map((column, i) => {
              const sorted = sort === column.key
              const canSort = column.sortable === true && onSort !== undefined
              return (
                <th
                  key={column.key}
                  scope="col"
                  // 정렬 상태를 화살표 글자로만 알리면 스크린리더에는 전달되지 않는다.
                  aria-sort={
                    canSort ? (sorted ? (desc ? 'descending' : 'ascending') : 'none') : undefined
                  }
                  className={`${pad} ${embedded ? 'font-normal' : 'font-medium'} ${
                    column.align === 'right' ? 'text-right' : 'text-left'
                  } ${column.hideBelow ? HIDE_BELOW[column.hideBelow] : ''} ${
                    stickyFirst && i === 0 ? 'sticky left-0 z-10 bg-neutral-900' : ''
                  }`}
                >
                  {canSort ? (
                    <button
                      type="button"
                      onClick={() => onSort(column.key)}
                      className="transition-colors hover:text-neutral-300"
                    >
                      {column.header}
                      {sorted && (
                        <span aria-hidden className="ml-0.5">
                          {desc ? '↓' : '↑'}
                        </span>
                      )}
                    </button>
                  ) : (
                    column.header
                  )}
                  {column.subHeader !== undefined && (
                    <div className="font-normal text-neutral-600">{column.subHeader}</div>
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody
          ref={bodyRef}
          className={embedded ? 'divide-y divide-neutral-900' : 'divide-y divide-neutral-800/70'}
        >
          {rows.map((row, index) => {
            const key = rowKey(row)
            const selected = key === selectedKey
            return (
              <tr
                key={key}
                aria-selected={selectable ? selected : undefined}
                tabIndex={selectable ? (index === focusIndex ? 0 : -1) : undefined}
                onKeyDown={selectable ? (event) => handleKey(event, index) : undefined}
                onClick={selectable ? () => onSelect(key) : undefined}
                className={`transition-colors ${selectable ? 'cursor-pointer' : ''} ${
                  selected
                    ? embedded
                      ? 'bg-neutral-800/60'
                      : 'bg-neutral-800/80'
                    : selectable
                      ? embedded
                        ? 'hover:bg-neutral-800/50'
                        : 'hover:bg-neutral-900/70'
                      : ''
                }`}
              >
                {columns.map((column, i) => (
                  <td
                    key={column.key}
                    className={`${pad} ${column.align === 'right' ? 'text-right' : ''} ${
                      column.hideBelow ? HIDE_BELOW[column.hideBelow] : ''
                    } ${
                      typeof column.cellClassName === 'function'
                        ? column.cellClassName(row)
                        : (column.cellClassName ?? '')
                    } ${
                      // 첫 열을 붙잡을 때는 바탕색을 직접 줘야 한다. 투명하면 밑으로
                      // 지나가는 다른 열이 비쳐 글자가 겹쳐 보인다.
                      stickyFirst && i === 0
                        ? `sticky left-0 z-10 ${selected ? 'bg-neutral-800' : 'bg-neutral-950'}`
                        : ''
                    }`}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
