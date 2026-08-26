import { useRef } from 'react'
import type { ReactNode } from 'react'

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
  /** 칸에 붙는 추가 클래스. 값에 따라 달라지면 함수로 준다(등락 색 등). */
  cellClassName?: string | ((row: T) => string)
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
  /** 이보다 좁아지면 가로로 스크롤한다. 숫자 칸이 줄바꿈되면 표가 흔들려 못 읽는다. */
  minWidth?: string
  /** 가로 스크롤 시 첫 열을 붙잡아 둔다. */
  stickyFirst?: boolean
  empty?: ReactNode
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  caption,
  selectedKey,
  onSelect,
  minWidth = 'min-w-[720px]',
  stickyFirst = false,
  empty = '조건에 맞는 항목이 없습니다.',
}: DataTableProps<T>) {
  const bodyRef = useRef<HTMLTableSectionElement>(null)

  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 p-8 text-center text-sm text-neutral-500">
        {empty}
      </div>
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
    <div className="overflow-x-auto rounded-lg border border-neutral-800">
      <table className={`w-full ${minWidth} text-sm whitespace-nowrap`}>
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-neutral-900 text-xs text-neutral-400">
          <tr>
            {columns.map((column, i) => (
              <th
                key={column.key}
                scope="col"
                className={`px-3 py-2 font-medium ${
                  column.align === 'right' ? 'text-right' : 'text-left'
                } ${stickyFirst && i === 0 ? 'sticky left-0 z-10 bg-neutral-900' : ''}`}
              >
                {column.header}
                {column.subHeader !== undefined && (
                  <div className="font-normal text-neutral-600">{column.subHeader}</div>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody ref={bodyRef} className="divide-y divide-neutral-800/70">
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
                  selected ? 'bg-neutral-800/80' : selectable ? 'hover:bg-neutral-900/70' : ''
                }`}
              >
                {columns.map((column, i) => (
                  <td
                    key={column.key}
                    className={`px-3 py-2 ${column.align === 'right' ? 'text-right' : ''} ${
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
