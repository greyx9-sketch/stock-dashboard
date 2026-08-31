import { useCallback, useEffect, useState } from 'react'
import { fetchMonthEvents, type CalendarEvent } from '../lib/api'
import { CalendarGrid } from '../components/calendar/CalendarGrid'
import { EventForm } from '../components/calendar/EventForm'
import { EventList } from '../components/calendar/EventList'
import { KIND_STYLE, dayOf, todayIso } from '../components/calendar/kinds'
import { Announce, ErrorBox, Loading } from '../components/ui/Status'

// 일정 캘린더. 기획서 5.3.
//
// **이 파일은 425 줄이었다.** 달력 격자·일정 목록·추가 폼·종류별 색이 한 덩어리로
// 들어 있었고, 카드 껍데기를 두 번 직접 그렸다. 넷으로 갈랐다 —
// `calendar/CalendarGrid` · `calendar/EventList` · `calendar/EventForm` · `calendar/kinds`.
// 여기 남은 것은 **어느 달을 보고 있는가**와 그 셋을 어디에 놓는가뿐이다.
//
// 일정은 두 갈래로 들어온다:
//   자동 — 금통위·FOMC(중앙은행 공표를 옮겨 적은 것) · 만기(KRX 규칙으로 계산)
//   직접 — 사용자가 적어 넣은 것. 이것만 지울 수 있다.

export function Calendar() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [picked, setPicked] = useState<string | null>(null)

  const today = todayIso()
  const isThisMonth = today.slice(0, 7) === `${year}-${String(month).padStart(2, '0')}`
  // 키보드가 짚고 있는 날. 이번 달이면 오늘부터, 아니면 1일부터 시작한다.
  const [cursor, setCursor] = useState(isThisMonth ? dayOf(today) : 1)

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
    // 달을 넘기면 짚고 있던 날이 없는 달일 수 있다(31일 → 2월). 1일로 되돌린다.
    setCursor(1)
  }

  const goToday = () => {
    const t = new Date()
    setYear(t.getFullYear())
    setMonth(t.getMonth() + 1)
    setPicked(null)
    setCursor(t.getDate())
  }

  const shown = picked ? events.filter((e) => e.event_date === picked) : events

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <button
            onClick={() => move(-1)}
            aria-label="이전 달"
            className="rounded border border-neutral-800 px-2 py-1 text-sm text-neutral-400 transition-colors hover:bg-neutral-800"
          >
            ←
          </button>
          <span className="tabular text-lg font-semibold">
            {year}년 {month}월
          </span>
          <button
            onClick={() => move(1)}
            aria-label="다음 달"
            className="rounded border border-neutral-800 px-2 py-1 text-sm text-neutral-400 transition-colors hover:bg-neutral-800"
          >
            →
          </button>
          <button
            onClick={goToday}
            className="rounded border border-neutral-800 px-2 py-1 text-xs text-neutral-400 transition-colors hover:bg-neutral-800"
          >
            오늘
          </button>
          {loading && <Loading label="불러오는 중…" />}
          {picked && (
            <button
              onClick={() => setPicked(null)}
              className="ml-auto rounded border border-neutral-800 px-2 py-1 text-xs text-neutral-400 transition-colors hover:bg-neutral-800"
            >
              <span className="tabular">{picked}</span> 만 보는 중 · 전체 보기
            </button>
          )}
        </div>

        {error && <ErrorBox tone="block" className="mb-3">{error}</ErrorBox>}

        {/* 달이 바뀌거나 날짜를 골랐다는 것을 소리로도 알린다. */}
        <Announce>
          {loading
            ? ''
            : picked
              ? `${picked} 일정 ${shown.length}건`
              : `${year}년 ${month}월 일정 ${events.length}건`}
        </Announce>

        <CalendarGrid
          year={year}
          month={month}
          events={events}
          picked={picked}
          onPick={setPicked}
          cursor={cursor}
          onCursor={setCursor}
          onMonth={move}
          today={today}
        />

        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-neutral-500">
          {Object.entries(KIND_STYLE).map(([kind, css]) => (
            <span key={kind} className="flex items-center gap-1">
              <span className={`size-1.5 rounded-full ${css.dot}`} />
              {kind}
            </span>
          ))}
        </div>

        <p className="mt-2 text-xs text-neutral-600">
          달력에서 화살표로 날짜를 옮기고, PageUp·PageDown 으로 달을 넘깁니다.
        </p>
      </div>

      <div className="space-y-4">
        <EventForm year={year} month={month} onAdded={reload} />
        <EventList events={shown} picked={picked} month={month} onChanged={reload} />
      </div>
    </div>
  )
}
