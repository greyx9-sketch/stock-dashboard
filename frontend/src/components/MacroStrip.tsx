import { useEffect, useState } from 'react'
import { fetchMacro } from '../lib/api'
import type { MacroItem } from '../lib/api'
import { changeColor } from '../lib/format'

// 화면 맨 위 매크로 띠. 국내·미국 탭이 같은 것을 쓴다.
//
// 값은 서버가 문자열로 다 다듬어 보낸다 — 여기서는 그리기만 한다. 지표마다 표기
// 자리수가 다르고(환율 1자리, 지수 2자리) 그 판단은 서버에 있다.
//
// 갱신 주기도 서버가 정한다(토스 10초, 시황·FRED 6시간 캐시). 화면은 그냥 주기적으로
// 부르면 되고, 캐시가 신선하면 서버가 외부를 부르지 않는다.

const REFRESH_MS = 30_000

export function MacroStrip() {
  const [items, setItems] = useState<MacroItem[]>([])
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false

    const load = () => {
      void fetchMacro()
        .then((r) => {
          if (cancelled) return
          setItems(r.items)
          // 지표가 하나도 없을 때만 실패로 본다. 일부가 빠진 것은 정상 동작이다 —
          // 서버가 나머지를 보내 주고 빠진 것은 목록에 없다.
          setFailed(r.items.length === 0)
        })
        .catch(() => {
          // 통째로 못 받았을 때만 자리를 비운다. 이전 값이 있으면 그대로 둔다.
          if (!cancelled) setFailed((prev) => (items.length === 0 ? true : prev))
        })
    }

    load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
    // items 를 의존성에 넣으면 30초마다 타이머가 다시 걸린다. 의도적으로 뺀다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 아직 못 받았고 실패도 아니면 아무것도 그리지 않는다. 빈 띠가 잠깐 보이는 것보다 낫다.
  if (items.length === 0) {
    if (!failed) return null
    return (
      <div className="border-b border-neutral-800 px-4 py-2 text-[11px] text-neutral-600">
        매크로 지표를 받지 못했습니다.
      </div>
    )
  }

  return (
    <div className="border-b border-neutral-800 bg-neutral-950/60">
      {/* 좁은 화면에서는 가로로 스크롤한다. 7개를 억지로 줄여 넣으면 숫자가 읽히지 않는다. */}
      <div className="flex gap-x-6 overflow-x-auto px-4 py-2">
        {items.map((item) => (
          <Cell key={item.code} item={item} />
        ))}
      </div>
    </div>
  )
}

function Cell({ item }: { item: MacroItem }) {
  const rate = item.change_rate
  // 등락률은 문자열이지만 색을 정하는 데만 숫자로 쓴다.
  const color = rate ? changeColor(rate) : 'text-neutral-500'

  return (
    <div className="flex shrink-0 items-baseline gap-1.5" title={tooltip(item)}>
      <span className="text-[11px] text-neutral-500">{item.label}</span>
      <span className="tabular text-sm text-neutral-200">
        {item.value}
        {item.unit && <span className="ml-0.5 text-[11px] text-neutral-500">{item.unit}</span>}
      </span>
      {rate && <span className={`tabular text-[11px] ${color}`}>{rate}%</span>}
      {/* 저장된 값을 보여주는 중이면 숨기지 않고 표시한다. 오래된 값을 최신처럼
          보여주는 것이 값이 없는 것보다 나쁘다. */}
      {item.stale && <span className="text-[10px] text-amber-500/70">갱신지연</span>}
    </div>
  )
}

function tooltip(item: MacroItem): string {
  const parts = [item.label]
  if (item.as_of) parts.push(`기준 ${item.as_of.slice(0, 19).replace('T', ' ')}`)
  if (item.source) parts.push(item.source)
  if (item.note) parts.push(item.note)
  if (item.stale) parts.push('지금 값을 받지 못해 마지막으로 받은 값을 보여주고 있습니다.')
  return parts.join(' · ')
}
