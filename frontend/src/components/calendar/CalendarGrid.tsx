import { useEffect, useRef } from 'react'
import type { CalendarEvent } from '../../lib/api'
import { WEEKDAYS, dayOf, isoOf, style } from './kinds'

// 한 달 격자. 사람이 이미 아는 모양이라, 그 모양을 벗어나면 날짜를 다시 세어 보게 된다.
//
// **키보드로 옮길 수 있어야 한다.** 예전에는 날짜 칸이 그냥 `<button>` 31 개였다.
// Tab 을 서른한 번 눌러야 달력을 지나갈 수 있었고, 그러고도 지금 몇 일에 있는지
// 화면에 표시가 없었다(3단계에서 포커스 링을 깔아 그건 해결됐다).
//
// 격자는 `role="grid"` 로 만든다. 화면을 읽어 주는 프로그램이 "행 3, 열 5" 처럼 위치를
// 말해 줄 수 있는 것은 이 역할이 붙어 있을 때뿐이다. 줄(`role="row"`)은 `display: contents`
// 라서 CSS 격자 배치는 그대로 남는다 — 줄 상자가 칸을 감싸도 화면은 안 바뀐다.
//
// 키:
//   ← →      하루씩
//   ↑ ↓      한 주씩
//   Home End 그 줄의 처음·끝
//   PageUp/Down  앞뒤 달 (달 경계에서 화살표가 넘어가지 않는 대신 이쪽을 쓴다 —
//                넘어가면 화면이 통째로 바뀌어서 어디로 갔는지 알기 어렵다)
//   Enter/Space  그 날짜만 보기 / 해제

type Props = {
  year: number
  month: number
  events: CalendarEvent[]
  /** 지금 "이 날짜만 보는 중"인 날. 없으면 전체를 본다. */
  picked: string | null
  onPick: (iso: string | null) => void
  /** 키보드로 짚고 있는 날. 격자에 들어오는 문은 이 칸 하나다. */
  cursor: number
  onCursor: (day: number) => void
  onMonth: (delta: number) => void
  today: string
}

export function CalendarGrid({
  year,
  month,
  events,
  picked,
  onPick,
  cursor,
  onCursor,
  onMonth,
  today,
}: Props) {
  const gridRef = useRef<HTMLDivElement>(null)
  // 키보드로 옮겼을 때만 진짜 포커스를 준다. 처음 화면이 뜰 때 달력으로 포커스가
  // 끌려가면 안 되므로, 격자 안에 이미 포커스가 있을 때만 옮긴다.
  const moved = useRef(false)

  // 날짜별로 묶는다. 칸을 그릴 때마다 전체를 훑지 않으려는 것이다.
  const byDay = new Map<number, CalendarEvent[]>()
  for (const event of events) {
    const day = dayOf(event.event_date)
    const bucket = byDay.get(day)
    if (bucket) bucket.push(event)
    else byDay.set(day, [event])
  }

  // 1일이 무슨 요일인지에 따라 앞을 비운다.
  const firstWeekday = new Date(year, month - 1, 1).getDay()
  const daysInMonth = new Date(year, month, 0).getDate()
  const cells: (number | null)[] = [
    ...Array<null>(firstWeekday).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ]
  while (cells.length % 7 !== 0) cells.push(null)

  const rows: (number | null)[][] = []
  for (let i = 0; i < cells.length; i += 7) rows.push(cells.slice(i, i + 7))

  const isThisMonth = today.slice(0, 7) === `${year}-${String(month).padStart(2, '0')}`
  const todayDay = isThisMonth ? dayOf(today) : -1

  useEffect(() => {
    if (!moved.current) return
    moved.current = false
    const target = gridRef.current?.querySelector<HTMLElement>(`[data-day="${cursor}"]`)
    target?.focus()
  }, [cursor, year, month])

  const go = (day: number) => {
    moved.current = true
    onCursor(Math.min(Math.max(day, 1), daysInMonth))
  }

  const handleKey = (event: React.KeyboardEvent, day: number) => {
    const weekday = (firstWeekday + day - 1) % 7
    switch (event.key) {
      case 'ArrowLeft':
        event.preventDefault()
        go(day - 1)
        break
      case 'ArrowRight':
        event.preventDefault()
        go(day + 1)
        break
      case 'ArrowUp':
        event.preventDefault()
        go(day - 7)
        break
      case 'ArrowDown':
        event.preventDefault()
        go(day + 7)
        break
      case 'Home':
        event.preventDefault()
        go(day - weekday)
        break
      case 'End':
        event.preventDefault()
        go(day + (6 - weekday))
        break
      case 'PageUp':
        event.preventDefault()
        moved.current = true
        onMonth(-1)
        break
      case 'PageDown':
        event.preventDefault()
        moved.current = true
        onMonth(1)
        break
    }
  }

  return (
    <div
      ref={gridRef}
      role="grid"
      aria-label={`${year}년 ${month}월 일정 달력`}
      className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border border-neutral-800 bg-neutral-800"
    >
      {/* `contents` 라서 줄 상자는 자리를 차지하지 않는다. 배치는 바깥 7열 격자가 그대로 한다. */}
      <div role="row" className="contents">
        {WEEKDAYS.map((name, i) => (
          <div
            key={name}
            role="columnheader"
            className={`bg-neutral-900 px-2 py-1.5 text-center text-xs ${
              i === 0 ? 'text-rose-400' : i === 6 ? 'text-sky-400' : 'text-neutral-500'
            }`}
          >
            {name}
          </div>
        ))}
      </div>

      {rows.map((row, rowIndex) => (
        <div role="row" className="contents" key={`row-${rowIndex}`}>
          {row.map((day, columnIndex) => {
            if (day === null) {
              return (
                <div
                  role="gridcell"
                  key={`blank-${rowIndex}-${columnIndex}`}
                  className="min-h-16 bg-neutral-950 sm:min-h-24"
                />
              )
            }

            const iso = isoOf(year, month, day)
            const dayEvents = byDay.get(day) ?? []
            const isToday = day === todayDay
            const isPicked = picked === iso

            return (
              <button
                role="gridcell"
                key={iso}
                data-day={day}
                // 격자 전체가 탭 정지 하나다. 들어와서는 화살표로 옮긴다.
                tabIndex={day === cursor ? 0 : -1}
                aria-selected={isPicked}
                // 칸 안의 글자는 "24" 뿐이라 소리로는 무슨 날인지 알 수 없다. 풀어서 읽힌다.
                aria-label={
                  `${month}월 ${day}일` +
                  (isToday ? ' 오늘' : '') +
                  (dayEvents.length > 0
                    ? ` · 일정 ${dayEvents.length}건: ${dayEvents.map((e) => e.title).join(', ')}`
                    : ' · 일정 없음')
                }
                onKeyDown={(event) => handleKey(event, day)}
                onClick={() => {
                  onCursor(day)
                  onPick(isPicked ? null : iso)
                }}
                className={`min-h-16 bg-neutral-900 p-1.5 text-left align-top transition-colors hover:bg-neutral-800/70 sm:min-h-24 ${
                  isPicked ? 'ring-1 ring-inset ring-neutral-500' : ''
                }`}
              >
                <span
                  className={`tabular text-xs ${
                    isToday
                      ? 'rounded bg-neutral-100 px-1 font-semibold text-neutral-900'
                      : columnIndex === 0
                        ? 'text-rose-400'
                        : columnIndex === 6
                          ? 'text-sky-400'
                          : 'text-neutral-400'
                  }`}
                >
                  {day}
                </span>
                {/* 휴대폰 칸은 50px 남짓이라 제목이 들어갈 자리가 없다. 점만 찍어
                    "이 날 뭔가 있다"만 알리고, 무엇인지는 아래 목록에서 본다.
                    소리로는 어차피 칸의 aria-label 이 제목까지 읽어 준다. */}
                <div className="mt-1 flex flex-wrap gap-1 sm:hidden" aria-hidden>
                  {dayEvents.slice(0, 4).map((event, i) => (
                    <span
                      key={`${iso}-dot-${i}`}
                      className={`size-1.5 rounded-full ${style(event.kind).dot}`}
                    />
                  ))}
                </div>

                <div className="mt-1 hidden space-y-0.5 sm:block" aria-hidden>
                  {dayEvents.slice(0, 3).map((event, i) => (
                    <div
                      key={`${iso}-${i}`}
                      className="flex items-center gap-1 text-[11px] leading-tight"
                    >
                      <span className={`size-1.5 shrink-0 rounded-full ${style(event.kind).dot}`} />
                      <span className="truncate text-neutral-300">{event.title}</span>
                    </div>
                  ))}
                  {dayEvents.length > 3 && (
                    <div className="text-[11px] text-neutral-600">+{dayEvents.length - 3}건</div>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      ))}
    </div>
  )
}
