import { useMemo, useState } from 'react'
import type { PricePoint } from '../lib/api'
import { formatShortDate, formatWon, formatRate, changeColor } from '../lib/format'

// 차트 라이브러리를 쓰지 않고 SVG 로 직접 그린다.
// 지금 필요한 것은 종가 선 하나뿐이라 라이브러리를 하나 더 붙일 이유가 없다.
// 봉차트·확대·보조지표가 필요해지면 그때 lightweight-charts 를 검토한다.

const WIDTH = 720
const HEIGHT = 240
const PADDING = { top: 16, right: 8, bottom: 24, left: 8 }

type Props = {
  points: PricePoint[]
}

export function PriceChart({ points }: Props) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)

  const geometry = useMemo(() => {
    if (points.length < 2) return null

    const closes = points.map((p) => p.close)
    const min = Math.min(...closes)
    const max = Math.max(...closes)
    // 값이 전부 같으면 높이가 0 이 되어 선이 사라진다. 최소 폭을 준다.
    const span = max - min || Math.max(max * 0.01, 1)

    const innerWidth = WIDTH - PADDING.left - PADDING.right
    const innerHeight = HEIGHT - PADDING.top - PADDING.bottom

    const xy = points.map((point, index) => ({
      x: PADDING.left + (index / (points.length - 1)) * innerWidth,
      y: PADDING.top + (1 - (point.close - min) / span) * innerHeight,
    }))

    const line = xy.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
    const area = `${line} L${xy[xy.length - 1].x.toFixed(1)},${HEIGHT - PADDING.bottom} L${xy[0].x.toFixed(1)},${HEIGHT - PADDING.bottom} Z`

    return { xy, line, area, min, max }
  }, [points])

  if (!geometry) {
    return (
      <div className="flex h-60 items-center justify-center rounded-lg border border-neutral-800 text-sm text-neutral-500">
        차트를 그리려면 거래일이 2일 이상 필요합니다.
      </div>
    )
  }

  // 기간 전체의 등락으로 선 색을 정한다. 국내 관례대로 상승 빨강 / 하락 파랑.
  const first = points[0].close
  const last = points[points.length - 1].close
  const rising = last >= first
  const stroke = rising ? 'var(--color-up)' : 'var(--color-down)'

  const active = hoverIndex !== null ? points[hoverIndex] : null
  const activePoint = hoverIndex !== null ? geometry.xy[hoverIndex] : null

  function handleMove(event: React.MouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    // SVG 는 화면 크기에 맞춰 늘어나므로, 실제 픽셀 위치를 좌표계로 되돌린다.
    const ratio = (event.clientX - rect.left) / rect.width
    const index = Math.round(ratio * (points.length - 1))
    setHoverIndex(Math.min(points.length - 1, Math.max(0, index)))
  }

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-3">
      <div className="mb-2 flex items-baseline justify-between text-xs text-neutral-400">
        <span>
          {active ? formatShortDate(active.trade_date) : `${points.length} 거래일`}
        </span>
        {active ? (
          <span className="tabular">
            <span className="text-neutral-100">{formatWon(active.close)}원</span>{' '}
            <span className={changeColor(active.change_rate)}>{formatRate(active.change_rate)}</span>
          </span>
        ) : (
          <span className="tabular">
            최고 {formatWon(geometry.max)} · 최저 {formatWon(geometry.min)}
          </span>
        )}
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIndex(null)}
        role="img"
        aria-label="일별 종가 차트"
      >
        <defs>
          <linearGradient id="priceArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.28" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>

        <path d={geometry.area} fill="url(#priceArea)" />
        <path d={geometry.line} fill="none" stroke={stroke} strokeWidth="2" strokeLinejoin="round" />

        {activePoint && (
          <g>
            <line
              x1={activePoint.x}
              y1={PADDING.top}
              x2={activePoint.x}
              y2={HEIGHT - PADDING.bottom}
              stroke="currentColor"
              strokeWidth="1"
              className="text-neutral-600"
            />
            <circle cx={activePoint.x} cy={activePoint.y} r="4" fill={stroke} />
          </g>
        )}

        {/* 양 끝 날짜만 축에 남긴다. 눈금을 촘촘히 넣으면 오히려 읽기 어렵다. */}
        <text x={PADDING.left} y={HEIGHT - 6} className="fill-neutral-500 text-[11px]">
          {formatShortDate(points[0].trade_date)}
        </text>
        <text
          x={WIDTH - PADDING.right}
          y={HEIGHT - 6}
          textAnchor="end"
          className="fill-neutral-500 text-[11px]"
        >
          {formatShortDate(points[points.length - 1].trade_date)}
        </text>
      </svg>
    </div>
  )
}
