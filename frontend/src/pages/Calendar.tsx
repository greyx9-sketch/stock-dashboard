import { useCallback, useEffect, useState } from 'react'
import {
  createEvent,
  deleteEvent,
  fetchMonthEvents,
  type CalendarEvent,
} from '../lib/api'

// 일정 캘린더. 기획서 5.3.
//
// 한 달을 7칸씩 끊어 그린다. 달력은 사람이 이미 아는 모양이라, 그 모양을 벗어나면
// 날짜를 다시 세어 보게 된다.
//
// 일정은 두 갈래로 들어온다:
//
//   자동 — 금통위·FOMC(중앙은행 공표를 옮겨 적은 것) · 만기(KRX 규칙으로 계산)
//   직접 — 사용자가 적어 넣은 것. 이것만 지울 수 있다.
//
// **자동인지 직접인지 화면에서 구분된다.** 직접 적은 것에만 지우기가 붙고, 아래 목록에
// 출처가 적힌다. 어디서 온 숫자인지 모르는 것을 화면에 두지 않는다는 이 프로젝트의
// 방침을 일정에도 그대로 적용한 것이다.

const KIND_STYLE: Record<string, { dot: string; text: string }> = {
  금통위: { dot: 'bg-amber-400', text: 'text-amber-300' },
  FOMC: { dot: 'bg-sky-400', text: 'text-sky-300' },
  만기: { dot: 'bg-violet-400', text: 'text-violet-300' },
  실적: { dot: 'bg-emerald-400', text: 'text-emerald-300' },
  배당: { dot: 'bg-rose-400', text: 'text-rose-300' },
  공모주: { dot: 'bg-orange-400', text: 'text-orange-300' },
  기타: { dot: 'bg-neutral-400', text: 'text-neutral-300' },
}

const CREATABLE = ['실적', '배당', '공모주', '기타']
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

function style(kind: string) {
  return KIND_STYLE[kind] ?? KIND_STYLE.기타
}

/** `2026-08-24` → 24. 시간대 때문에 Date 로 바꾸지 않고 문자열에서 바로 뗀다. */
function dayOf(iso: string): number {
  return Number(iso.slice(8, 10))
}

function todayIso(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export function Calendar() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [picked, setPicked] = useState<string | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    fetchMonthEvents(year, month)
      .then((result) => {
        setEvents(result.events)
        setError(null)
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [year, month])

  useEffect(reload, [reload])

  const move = (delta: number) => {
    const next = month + delta
    if (next < 1) {
      setYear(year - 1)
      setMonth(12)
    } else if (next > 12) {
      setYear(year + 1)
      setMonth(1)
    } else {
      setMonth(next)
    }
    setPicked(null)
  }

  const goToday = () => {
    const t = new Date()
    setYear(t.getFullYear())
    setMonth(t.getMonth() + 1)
    setPicked(null)
  }

  // 날짜별로 묶는다. 칸을 그릴 때마다 전체를 훑지 않으려는 것이다.
  const byDay = new Map<number, CalendarEvent[]>()
  for (const event of events) {
    const day = dayOf(event.event_date)
    const bucket = byDay.get(day)
    if (bucket) bucket.push(event)
    else byDay.set(day, [event])
  }

  // 달력 격자. 1일이 무슨 요일인지에 따라 앞을 비운다.
  const firstWeekday = new Date(year, month - 1, 1).getDay()
  const daysInMonth = new Date(year, month, 0).getDate()
  const cells: (number | null)[] = [
    ...Array<null>(firstWeekday).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ]
  while (cells.length % 7 !== 0) cells.push(null)

  const today = todayIso()
  const isThisMonth = today.slice(0, 7) === `${year}-${String(month).padStart(2, '0')}`
  const todayDay = isThisMonth ? dayOf(today) : -1

  const shown = picked
    ? events.filter((e) => e.event_date === picked)
    : events

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <button
            onClick={() => move(-1)}
            className="rounded border border-neutral-800 px-2 py-1 text-sm text-neutral-400 hover:bg-neutral-800"
          >
            ←
          </button>
          <span className="tabular text-lg font-semibold">
            {year}년 {month}월
          </span>
          <button
            onClick={() => move(1)}
            className="rounded border border-neutral-800 px-2 py-1 text-sm text-neutral-400 hover:bg-neutral-800"
          >
            →
          </button>
          <button
            onClick={goToday}
            className="rounded border border-neutral-800 px-2 py-1 text-xs text-neutral-400 hover:bg-neutral-800"
          >
            오늘
          </button>
          {loading && <span className="text-xs text-neutral-600">불러오는 중…</span>}
          {picked && (
            <button
              onClick={() => setPicked(null)}
              className="ml-auto rounded border border-neutral-800 px-2 py-1 text-xs text-neutral-400 hover:bg-neutral-800"
            >
              {picked} 만 보는 중 · 전체 보기
            </button>
          )}
        </div>

        {error && (
          <div className="mb-3 rounded border border-rose-900 bg-rose-950/40 px-3 py-2 text-xs text-rose-300">
            {error}
          </div>
        )}

        <div className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border border-neutral-800 bg-neutral-800">
          {WEEKDAYS.map((name, i) => (
            <div
              key={name}
              className={`bg-neutral-900 px-2 py-1.5 text-center text-xs ${
                i === 0 ? 'text-rose-400' : i === 6 ? 'text-sky-400' : 'text-neutral-500'
              }`}
            >
              {name}
            </div>
          ))}

          {cells.map((day, index) => {
            if (day === null) {
              return <div key={`blank-${index}`} className="min-h-24 bg-neutral-950/60" />
            }
            const iso = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
            const dayEvents = byDay.get(day) ?? []
            const isToday = day === todayDay
            return (
              <button
                key={iso}
                onClick={() => setPicked(picked === iso ? null : iso)}
                className={`min-h-24 bg-neutral-900 p-1.5 text-left align-top transition-colors hover:bg-neutral-800/70 ${
                  picked === iso ? 'ring-1 ring-inset ring-neutral-500' : ''
                }`}
              >
                <span
                  className={`tabular text-xs ${
                    isToday
                      ? 'rounded bg-neutral-100 px-1 font-semibold text-neutral-900'
                      : index % 7 === 0
                        ? 'text-rose-400'
                        : index % 7 === 6
                          ? 'text-sky-400'
                          : 'text-neutral-400'
                  }`}
                >
                  {day}
                </span>
                <div className="mt-1 space-y-0.5">
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

        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-neutral-500">
          {Object.entries(KIND_STYLE).map(([kind, css]) => (
            <span key={kind} className="flex items-center gap-1">
              <span className={`size-1.5 rounded-full ${css.dot}`} />
              {kind}
            </span>
          ))}
        </div>
      </div>

      <div className="space-y-4">
        <EventForm year={year} month={month} onAdded={reload} />

        <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
          <div className="border-b border-neutral-800 px-3 py-2 text-xs text-neutral-400">
            {picked ? `${picked} 일정` : `${month}월 일정`}
            <span className="ml-1 text-neutral-600">{shown.length}건</span>
          </div>
          {shown.length === 0 ? (
            <p className="px-3 py-4 text-xs text-neutral-500">일정이 없습니다.</p>
          ) : (
            <ul className="divide-y divide-neutral-800">
              {shown.map((event, i) => (
                <EventRow
                  key={`${event.event_date}-${i}`}
                  event={event}
                  onDeleted={reload}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

function EventRow({ event, onDeleted }: { event: CalendarEvent; onDeleted: () => void }) {
  // 지우기는 두 번 눌러야 지워진다. 메모와 같은 방식이다 — 되돌릴 수 없는 데이터라서.
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const remove = () => {
    if (!confirming) {
      setConfirming(true)
      return
    }
    if (event.id === null) return
    setBusy(true)
    deleteEvent(event.id)
      .then(onDeleted)
      .finally(() => setBusy(false))
  }

  return (
    <li className="group px-3 py-2">
      <div className="flex items-start gap-2">
        <span className={`mt-1.5 size-1.5 shrink-0 rounded-full ${style(event.kind).dot}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="tabular text-xs text-neutral-500">{event.event_date.slice(5)}</span>
            <span className={`text-[11px] ${style(event.kind).text}`}>{event.kind}</span>
          </div>
          <div className="text-xs text-neutral-200">{event.title}</div>
          {event.symbol && (
            <div className="text-[11px] text-neutral-500">{event.symbol}</div>
          )}
          {event.memo && (
            <div className="mt-0.5 text-[11px] text-neutral-500">{event.memo}</div>
          )}
          {event.source && (
            <div className="mt-0.5 text-[11px] text-neutral-600">
              {event.source}
              {event.source_url && (
                <>
                  {' · '}
                  <a
                    href={event.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="whitespace-nowrap underline decoration-neutral-700 underline-offset-2 hover:text-neutral-400"
                  >
                    원문
                  </a>
                </>
              )}
            </div>
          )}
        </div>
        {event.editable && (
          <button
            onClick={remove}
            onBlur={() => setConfirming(false)}
            disabled={busy}
            className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] transition-colors ${
              confirming
                ? 'bg-rose-900/60 text-rose-200'
                : 'text-neutral-600 opacity-0 hover:text-neutral-300 group-hover:opacity-100'
            }`}
          >
            {confirming ? '정말 지울까요?' : '지우기'}
          </button>
        )}
      </div>
    </li>
  )
}

function EventForm({
  year,
  month,
  onAdded,
}: {
  year: number
  month: number
  onAdded: () => void
}) {
  const [date, setDate] = useState('')
  const [kind, setKind] = useState(CREATABLE[0])
  const [title, setTitle] = useState('')
  const [symbol, setSymbol] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // 보고 있는 달로 기본값을 맞춘다. 8월을 펼쳐 놓고 일정을 적는데 날짜가 오늘 달로
  // 잡혀 있으면 매번 고쳐야 한다.
  useEffect(() => {
    setDate(`${year}-${String(month).padStart(2, '0')}-01`)
  }, [year, month])

  const submit = () => {
    if (!title.trim()) return
    setBusy(true)
    setError(null)
    createEvent({
      event_date: date,
      kind,
      title: title.trim(),
      symbol: symbol.trim() || null,
    })
      .then(() => {
        setTitle('')
        setSymbol('')
        onAdded()
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div className="border-b border-neutral-800 px-3 py-2 text-xs text-neutral-400">
        일정 추가
        <span className="ml-1 text-neutral-600">실적·배당 예정일처럼 직접 아는 것</span>
      </div>
      <div className="space-y-2 p-3">
        <div className="flex gap-2">
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="tabular min-w-0 flex-1 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs text-neutral-200"
          />
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs text-neutral-200"
          >
            {CREATABLE.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
          }}
          placeholder="무슨 일정인지 (예: 삼성전자 3분기 실적)"
          className="w-full rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600"
        />
        <div className="flex gap-2">
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="종목코드 (선택)"
            className="min-w-0 flex-1 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-600"
          />
          <button
            onClick={submit}
            disabled={busy || !title.trim()}
            className="rounded bg-neutral-100 px-3 py-1 text-xs text-neutral-900 disabled:opacity-40"
          >
            저장
          </button>
        </div>
        {error && <p className="text-[11px] text-rose-400">{error}</p>}
      </div>
    </div>
  )
}
