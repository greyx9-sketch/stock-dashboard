import { useEffect, useState } from 'react'
import { createEvent } from '../../lib/api'
import { Card } from '../ui/Card'
import { ErrorBox } from '../ui/Status'
import { CREATABLE, isoOf } from './kinds'

// 일정 직접 추가. 자동으로 들어오는 것(금통위·FOMC·만기) 말고 사용자가 아는 것만 여기서 만든다.

type Props = {
  year: number
  month: number
  onAdded: () => void
}

export function EventForm({ year, month, onAdded }: Props) {
  const [date, setDate] = useState('')
  const [kind, setKind] = useState(CREATABLE[0])
  const [title, setTitle] = useState('')
  const [symbol, setSymbol] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // 보고 있는 달로 기본값을 맞춘다. 8월을 펼쳐 놓고 일정을 적는데 날짜가 오늘 달로
  // 잡혀 있으면 매번 고쳐야 한다.
  useEffect(() => {
    setDate(isoOf(year, month, 1))
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
    <Card title="일정 추가" hint="실적·배당 예정일처럼 직접 아는 것" bodyClassName="space-y-2 p-3">
      <div className="flex gap-2">
        <input
          type="date"
          aria-label="날짜"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="tabular min-w-0 flex-1 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-200"
        />
        <select
          aria-label="일정 종류"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-200"
        >
          {CREATABLE.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>
      <input
        aria-label="일정 제목"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
        placeholder="무슨 일정인지 (예: 삼성전자 3분기 실적)"
        className="w-full rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-200 placeholder:text-neutral-600"
      />
      <div className="flex gap-2">
        <input
          aria-label="종목코드 (선택)"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="종목코드 (선택)"
          className="tabular min-w-0 flex-1 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-200 placeholder:text-neutral-600"
        />
        <button
          onClick={submit}
          disabled={busy || !title.trim()}
          className="rounded bg-neutral-100 px-3 py-1 text-sm text-neutral-900 transition-colors hover:bg-white disabled:opacity-40"
        >
          {busy ? '저장 중…' : '저장'}
        </button>
      </div>
      {error && <ErrorBox>{error}</ErrorBox>}
    </Card>
  )
}
