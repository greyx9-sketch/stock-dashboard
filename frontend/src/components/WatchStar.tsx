import { useState } from 'react'
import { toggle, useIsWatched } from '../lib/watchlistStore'

// 관심종목 담기/빼기 버튼. 국내·미국 상세 화면의 종목명 옆에 붙는다.
//
// 목록의 표에는 넣지 않았다. 표는 이미 열이 일곱 개라 한 열을 더 넣으면 좁은 화면에서
// 종목명이 잘린다. 상세를 열어 보고 담는 흐름이 실제 사용 순서에도 맞는다.

type Props = {
  symbol: string
}

export function WatchStar({ symbol }: Props) {
  const watched = useIsWatched(symbol)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const onClick = () => {
    if (busy) return
    setBusy(true)
    setError(null)
    toggle(symbol)
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        onClick={onClick}
        disabled={busy}
        // 상한(60개)을 넘겼을 때처럼 서버가 거절한 이유는 title 로 보여준다.
        title={error ?? (watched ? '관심종목에서 빼기' : '관심종목에 담기')}
        aria-pressed={watched}
        className={`rounded px-1.5 py-0.5 text-base leading-none transition-colors ${
          watched
            ? 'text-amber-400 hover:text-amber-300'
            : 'text-neutral-600 hover:text-neutral-300'
        } ${busy ? 'opacity-50' : ''}`}
      >
        {watched ? '★' : '☆'}
      </button>
      {error && <span className="text-xs text-red-400">{error}</span>}
    </span>
  )
}
