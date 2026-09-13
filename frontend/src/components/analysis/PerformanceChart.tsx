import { useMemo } from 'react'

/* 실적 추이 — 보고서 안에 놓는 세로 막대 그래프.
 *
 * ── 재무 탭의 표와 무엇이 다른가 ──────────────────────────────────────
 * `FinancialBars` 는 **표**다. 연도·막대·수치·마진·성장률이 한 줄에 놓여 값을 읽는 데
 * 쓴다. 이 그림은 **모양**을 보는 것이다 — 매출이 꺾였는지, 이익이 매출보다 먼저
 * 움직였는지, 적자 해가 있었는지. 보고서를 읽다가 "그래서 이 회사 실적이 어땠는데"가
 * 나오는 자리에 값이 아니라 모양이 필요하다.
 *
 * 그래서 여기서는 눈금을 그리지 않고 값도 막대 위에 한 번만 적는다. 정확한 숫자가
 * 필요하면 재무 탭으로 가야 하고, 각주에 그렇게 적어 둔다.
 *
 * ── 여기서는 SVG 를 쓴다 ──────────────────────────────────────────────
 * 옆의 도식들은 격자로 그렸다. **좌표가 글자 길이에서 나오기** 때문이다. 이 그림은
 * 반대로 좌표가 숫자에서 나온다 — 막대 높이가 매출에 비례해야 하고, 그건 CSS 로는
 * 흉내만 낼 수 있다. 프로젝트의 다른 차트(`PriceChart`)와 같은 방식이다.
 *
 * ── 축을 하나만 쓴다 ──────────────────────────────────────────────────
 * 영업이익률을 두 번째 축으로 겹치지 않는다(`FinancialBars` 가 정해 둔 규칙).
 * 단위가 다른 둘을 한 그림에 겹치면 두 선의 교차가 아무 뜻도 없는 그림이 된다.
 * 마진은 막대 아래 숫자로 적는다.
 *
 * ── 색 ────────────────────────────────────────────────────────────────
 * 매출은 크기만 나타내므로 중립색, 이익은 부호가 뜻을 가지므로 국내 관례대로
 * 흑자 빨강 / 적자 파랑. `FinancialBars` 와 같은 규칙을 쓴다 — 한 화면 안에서
 * 같은 뜻에 다른 색을 쓰면 둘 다 뜻을 잃는다.
 */

export type PerformancePoint = {
  /** 가로축에 놓을 이름. 예: '2025' */
  label: string
  revenue: number | null
  operatingIncome: number | null
  /** 옆에 적을 영업이익률. 서버가 계산한 문자열 그대로. */
  operatingMargin: string | null
}

type Props = {
  points: PerformancePoint[]
  /** 금액을 사람이 읽는 말로. 국내는 조·억, 미국은 T·B. */
  formatAmount: (value: number) => string
}

// SVG 는 높이에 맞춰 그림 전체를 줄이므로, viewBox 가 좁으면 막대까지 가늘어진다.
// 그래서 viewBox 를 높이 대비 넉넉히 잡고(64 × 136) 막대를 그 안에서 굵게 그린다.
const HEIGHT = 132
const LABEL_BAND = 4 // 0 선 아래로 적자 막대가 내려갈 자리 비율

export function PerformanceChart({ points, formatAmount }: Props) {
  const rows = points.filter((p) => p.revenue !== null || p.operatingIncome !== null)

  const scale = useMemo(() => {
    const values = rows.flatMap((p) =>
      [p.revenue, p.operatingIncome].filter((v): v is number => v !== null),
    )
    if (values.length === 0) return null
    const max = Math.max(...values, 0)
    const min = Math.min(...values, 0)
    // 값이 전부 0 이면 높이가 0 이 되어 막대가 사라진다. 최소 폭을 준다.
    const span = max - min || Math.max(Math.abs(max), 1)
    return { max, min, span }
  }, [rows])

  if (!scale || rows.length === 0) return null

  // 0 선의 위치. 적자가 없으면 바닥에 붙는다.
  const zeroY = (scale.max / scale.span) * HEIGHT

  const barHeight = (value: number) => (Math.abs(value) / scale.span) * HEIGHT
  const barTop = (value: number) => (value >= 0 ? zeroY - barHeight(value) : zeroY)

  return (
    <figure className="m-0">
      <div className="flex items-end gap-2 overflow-x-auto pb-1">
        {rows.map((point) => (
          <div key={point.label} className="flex min-w-[64px] flex-1 flex-col items-center">
            {/* 막대 한 쌍. 두 값이 같은 축을 쓰므로 높이를 직접 견줄 수 있다. */}
            <svg
              viewBox={`0 0 64 ${HEIGHT + LABEL_BAND}`}
              className="h-[132px] w-full"
              role="img"
              aria-label={`${point.label} 매출 ${
                point.revenue === null ? '없음' : formatAmount(point.revenue)
              }, 영업이익 ${
                point.operatingIncome === null ? '없음' : formatAmount(point.operatingIncome)
              }`}
            >
              {point.revenue !== null && (
                <rect
                  x="8"
                  y={barTop(point.revenue)}
                  width="20"
                  height={Math.max(barHeight(point.revenue), 1)}
                  rx="1.5"
                  className="fill-bar"
                />
              )}
              {point.operatingIncome !== null && (
                <rect
                  x="36"
                  y={barTop(point.operatingIncome)}
                  width="20"
                  height={Math.max(barHeight(point.operatingIncome), 1)}
                  rx="1.5"
                  className={point.operatingIncome >= 0 ? 'fill-up' : 'fill-down'}
                />
              )}
              {/* 0 선. 적자 해가 있을 때만 뜻이 생기므로 그때만 그린다. */}
              {scale.min < 0 && (
                <line
                  x1="0"
                  x2="64"
                  y1={zeroY}
                  y2={zeroY}
                  className="stroke-neutral-700"
                  strokeWidth="0.5"
                />
              )}
            </svg>

            <div className="mt-1 text-center">
              <div className="text-[11px] font-medium tabular text-neutral-300">
                {point.label}
              </div>
              <div className="text-[10px] tabular leading-relaxed text-neutral-500">
                {point.revenue === null ? '—' : formatAmount(point.revenue)}
              </div>
              {point.operatingMargin && (
                <div className="text-[10px] tabular leading-relaxed text-neutral-600">
                  {point.operatingMargin}%
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <figcaption className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-neutral-600">
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2 rounded-[1px] bg-bar" />
          매출
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2 rounded-[1px] bg-up" />
          영업이익
        </span>
        <span>아래 숫자는 매출과 영업이익률입니다. 정확한 값은 재무 탭에 있습니다.</span>
      </figcaption>
    </figure>
  )
}
