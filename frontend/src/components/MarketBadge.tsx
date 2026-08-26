import type { MarketState } from '../lib/api'
import { formatTimestamp } from '../lib/format'

// 지금 장이 열려 있는지, 화면 숫자가 움직이는 값인지 한눈에 알리는 표시.
// 마감 뒤에 멈춘 숫자를 실시간으로 착각하지 않게 하는 것이 목적이다.

const DOT_STYLE: Record<string, string> = {
  REGULAR: 'bg-emerald-400',
  PRE: 'bg-amber-400',
  AFTER: 'bg-amber-400',
  CLOSED: 'bg-neutral-500',
  HOLIDAY: 'bg-neutral-500',
  // 대비를 맞추며 500 과 600 이 가까워졌다. "상태를 모름"은 마감과 구별돼야 하므로 한 단 내린다.
  UNKNOWN: 'bg-neutral-700',
}

type Props = {
  market: MarketState | null
  error: string | null
  /** 웹소켓으로 들어오는 중인가. 붙지 않았을 때도 폴링으로 값은 그대로 나온다. */
  realtime?: boolean
}

export function MarketBadge({ market, error, realtime = false }: Props) {
  if (error) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-red-900/60 bg-red-950/40 px-2.5 py-1 text-xs text-red-300">
        <span className="size-1.5 rounded-full bg-red-400" />
        현재가 연결 끊김
      </span>
    )
  }

  if (!market) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-neutral-800 px-2.5 py-1 text-xs text-neutral-500">
        <span className="size-1.5 rounded-full bg-neutral-600" />
        확인 중
      </span>
    )
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-neutral-800 bg-neutral-900 px-2.5 py-1 text-xs text-neutral-300">
      <span
        className={`size-1.5 rounded-full ${DOT_STYLE[market.phase] ?? DOT_STYLE.UNKNOWN} ${
          market.is_live ? 'animate-pulse' : ''
        }`}
      />
      {market.label}
      <span className="text-neutral-500">
        {market.is_live
          ? realtime
            ? '· 실시간'
            : '· 1초마다 갱신'
          : market.next_open
            ? `· 다음 개장 ${formatTimestamp(market.next_open)}`
            : ''}
      </span>
    </span>
  )
}
