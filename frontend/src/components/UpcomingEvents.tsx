import { useEffect, useState } from 'react'
import { fetchUpcomingEvents, type Upcoming } from '../lib/api'

// 다가오는 일정 띠. 기획서 5.1 — "다가오는 일정 3~5건".
//
// **매크로 띠 바로 아래, 탭 위**에 둔다. 시장을 오가도 그대로 보여야 하는 정보라서다 —
// 금통위가 이틀 뒤라는 사실은 국내를 보든 미국을 보든 똑같이 중요하다.
//
// **D-day 를 서버에서 받아 온다.** 브라우저에서 날짜를 빼면 시간대가 다를 때 하루
// 어긋난다. 서버가 한국 시간으로 세어 `days_away` 로 주고, 여기서는 말로 바꾸기만 한다.
//
// 일정이 없으면 **아무것도 그리지 않는다.** 빈 띠를 남기면 화면만 좁아진다.

const KIND_DOT: Record<string, string> = {
  금통위: 'bg-amber-400',
  FOMC: 'bg-sky-400',
  만기: 'bg-violet-400',
  실적: 'bg-emerald-400',
  배당: 'bg-rose-400',
  공모주: 'bg-orange-400',
  기타: 'bg-neutral-400',
}

/** 며칠 뒤인지를 사람 말로. 오늘·내일은 숫자보다 말이 빠르게 읽힌다. */
function whenLabel(days: number): string {
  if (days <= 0) return '오늘'
  if (days === 1) return '내일'
  return `D-${days}`
}

export function UpcomingEvents() {
  const [items, setItems] = useState<Upcoming[]>([])

  useEffect(() => {
    let cancelled = false
    fetchUpcomingEvents(60, 4)
      .then((result) => {
        if (!cancelled) setItems(result)
      })
      .catch(() => {
        // 곁다리다. 실패해도 화면의 나머지는 그대로 뜬다.
        if (!cancelled) setItems([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (items.length === 0) return null

  return (
    <div className="border-b border-neutral-900 bg-neutral-950/60">
      {/* 휴대폰에서는 줄바꿈 대신 옆으로 민다. 네 건이 네 줄이 되면 화면 위쪽을
          통째로 차지해서 정작 시세가 안 보인다. */}
      <div className="mx-auto flex max-w-7xl flex-nowrap items-center gap-x-4 gap-y-1 overflow-x-auto px-3 py-1.5 text-xs sm:flex-wrap sm:px-4">
        <span className="shrink-0 text-neutral-600">다가오는 일정</span>
        {items.map(({ event, days_away }) => (
          <span
            key={`${event.event_date}-${event.title}`}
            className="flex shrink-0 items-center gap-1.5 whitespace-nowrap"
          >
            <span className={`size-1.5 rounded-full ${KIND_DOT[event.kind] ?? KIND_DOT.기타}`} />
            <span className="tabular text-neutral-500">{event.event_date.slice(5)}</span>
            <span className="text-neutral-300">{event.title}</span>
            <span
              className={`tabular ${
                // 오늘·내일만 도드라지게 한다. 전부 강조하면 아무것도 강조되지 않는다.
                days_away <= 1 ? 'text-neutral-100' : 'text-neutral-600'
              }`}
            >
              {whenLabel(days_away)}
            </span>
          </span>
        ))}
      </div>
    </div>
  )
}
