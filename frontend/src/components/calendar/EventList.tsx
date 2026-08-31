import { useState } from 'react'
import { deleteEvent, type CalendarEvent } from '../../lib/api'
import { Card } from '../ui/Card'
import { Empty } from '../ui/Status'
import { style } from './kinds'

// 일정 목록. 달력 칸에는 세 건까지만 들어가므로, 그 달의 전부를 여기서 본다.
//
// **자동인지 직접인지 화면에서 구분된다.** 직접 적은 것에만 지우기가 붙고, 자동으로
// 들어온 것에는 출처가 적힌다. 어디서 온 값인지 모르는 것을 화면에 두지 않는다는
// 이 프로젝트의 방침을 일정에도 그대로 적용한 것이다.

type Props = {
  events: CalendarEvent[]
  /** 특정 날짜만 보는 중이면 그 날짜. 머리글 문구가 달라진다. */
  picked: string | null
  month: number
  onChanged: () => void
}

export function EventList({ events, picked, month, onChanged }: Props) {
  return (
    <Card
      title={picked ? `${picked} 일정` : `${month}월 일정`}
      meta={<span className="tabular">{events.length}건</span>}
      bodyClassName=""
    >
      {events.length === 0 ? (
        <Empty
          className="px-3 py-4"
          title="일정이 없습니다."
          hint={picked ? '다른 날짜를 눌러 보거나 전체 보기로 돌아가세요.' : undefined}
        />
      ) : (
        <ul className="divide-y divide-neutral-800">
          {events.map((event, i) => (
            <EventRow key={`${event.event_date}-${i}`} event={event} onDeleted={onChanged} />
          ))}
        </ul>
      )}
    </Card>
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
            <span className={`text-xs ${style(event.kind).text}`}>{event.kind}</span>
          </div>
          <div className="text-sm text-neutral-200">{event.title}</div>
          {event.symbol && <div className="tabular text-xs text-neutral-500">{event.symbol}</div>}
          {event.memo && <div className="mt-0.5 text-xs text-neutral-500">{event.memo}</div>}
          {event.source && (
            <div className="mt-0.5 text-xs text-neutral-600">
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
            // 화면에는 "지우기" 두 글자면 충분하다(옆에 제목이 보인다). 소리로 들을 때는
            // 어느 일정의 지우기인지 알 수 없으므로 제목을 붙여 읽힌다.
            aria-label={confirming ? `${event.title} 정말 지울까요?` : `${event.title} 지우기`}
            // 마우스를 올렸을 때만 보이던 것을 키보드 포커스에서도 보이게 한다.
            // 안 그러면 Tab 으로 닿기는 하는데 눈에는 안 보이는 버튼이 된다.
            className={`shrink-0 rounded px-1.5 py-0.5 text-xs transition-colors ${
              confirming
                ? 'bg-rose-900/60 text-rose-200'
                : 'text-neutral-600 opacity-0 hover:text-neutral-300 focus-visible:opacity-100 group-hover:opacity-100'
            }`}
          >
            {confirming ? '정말 지울까요?' : '지우기'}
          </button>
        )}
      </div>
    </li>
  )
}
