import { useMemo, useState } from 'react'

// 연간 재무 추이를 그리는 부분. 국내(DART)와 미국(SEC)이 이 컴포넌트를 함께 쓴다.
//
// 형태 선택: 값 하나를 연도(순서형 축)에 걸쳐 비교하는 일이라 막대가 맞다. 다만 패널이
// 좁아서 세로 막대 대신 **막대가 들어간 표**로 만들었다 — 연도·막대·수치가 한 줄에 놓여
// 여러 연도가 전부 보이고, 표 자체가 곧 데이터 테이블 역할을 한다.
//
// 축은 하나만 쓴다. 영업이익률을 같은 그림에 두 번째 축으로 겹치지 않고 옆의 숫자로 적는다.
// (단위가 다른 둘을 한 그림에 겹치면 두 선의 교차가 아무 뜻도 없는 그림이 된다.)
//
// 색: 매출은 크기만 나타내므로 중립색. 이익은 부호가 뜻을 가지므로 국내 관례대로
// 흑자 빨강 / 적자 파랑. 두 색은 색각 이상 시뮬레이션에서 충분히 구분된다(ΔE 25.0).

export type FinancialRow = {
  /** 표에 쓸 연도 이름 */
  label: string
  /** 회계연도 종료일처럼 연도만으로 부족할 때 덧붙이는 설명 */
  sublabel?: string
  revenue: number | null
  operating_income: number | null
  net_income: number | null
  total_assets: number | null
  operating_margin: string | null
  revenue_growth: string | null
  roe: string | null
  debt_ratio: string | null
  source_url: string
}

export type MetricKey = 'revenue' | 'operating_income' | 'net_income'

const METRICS: { key: MetricKey; label: string; polar: boolean }[] = [
  { key: 'revenue', label: '매출', polar: false },
  { key: 'operating_income', label: '영업이익', polar: true },
  { key: 'net_income', label: '순이익', polar: true },
]

type Props = {
  rows: FinancialRow[]
  /** 금액을 사람이 읽는 형태로. 국내는 조·억, 미국은 B·M 로 다르다. */
  formatMoney: (value: number) => string
  /** 수준을 나타내는 비율. 부호를 붙이지 않는다. */
  formatPct: (value: string | null) => string
  /** 변화를 나타내는 비율. 부호를 붙인다. */
  formatDelta: (value: string | null) => string
  /** 오른쪽 위에 붙는 설명 (연결/별도, 10-K 등) */
  badge?: string
  /** 맨 아래 출처 설명 */
  footnote?: string
}

export function FinancialBars({
  rows,
  formatMoney,
  formatPct,
  formatDelta,
  badge,
  footnote,
}: Props) {
  // 매출 계정이 없는 회사(금융지주·은행)는 매출 막대가 전부 비어 버린다. 그럴 땐 영업이익으로 연다.
  const firstUsable: MetricKey = rows.some((r) => r.revenue !== null)
    ? 'revenue'
    : rows.some((r) => r.operating_income !== null)
      ? 'operating_income'
      : 'net_income'

  const [metric, setMetric] = useState<MetricKey>(firstUsable)
  const [hovered, setHovered] = useState<string | null>(null)

  const active = METRICS.find((m) => m.key === metric) ?? METRICS[0]

  // 막대 길이는 절댓값의 최댓값을 기준으로 잡는다. 적자가 섞여 있어도 크기 비교가 된다.
  const scale = useMemo(() => {
    const values = rows.map((r) => Math.abs(r[metric] ?? 0))
    return Math.max(...values, 1)
  }, [rows, metric])

  if (rows.length === 0) return null

  const latest = rows[rows.length - 1]

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div className="flex flex-wrap items-center gap-1 border-b border-neutral-800 px-3 py-2">
        <span className="mr-1 text-xs text-neutral-400">연간 재무</span>
        {METRICS.map((option) => (
          <button
            key={option.key}
            onClick={() => setMetric(option.key)}
            className={`rounded px-2 py-0.5 text-xs transition-colors ${
              metric === option.key
                ? 'bg-neutral-100 text-neutral-900'
                : 'text-neutral-400 hover:bg-neutral-800'
            }`}
          >
            {option.label}
          </button>
        ))}
        {badge && <span className="ml-auto text-xs text-neutral-600">{badge}</span>}
      </div>

      <div className="px-3 py-2">
        {rows.map((row) => {
          const value = row[metric]
          const ratio = value === null ? 0 : Math.abs(value) / scale
          const negative = (value ?? 0) < 0
          const color = !active.polar
            ? 'var(--color-bar)'
            : negative
              ? 'var(--color-down)'
              : 'var(--color-up)'

          return (
            <div
              key={row.label}
              onMouseEnter={() => setHovered(row.label)}
              onMouseLeave={() => setHovered(null)}
              className="relative -mx-1 rounded px-1 py-1 transition-colors hover:bg-neutral-800/50"
            >
              <div className="flex items-baseline gap-2 text-xs">
                <span className="tabular w-9 shrink-0 text-neutral-500">{row.label}</span>
                {/* 막대는 기준선에 붙고 끝만 둥글다. 값이 없으면 그리지 않는다. */}
                <span className="h-2.5 min-w-0 flex-1 rounded-sm bg-neutral-800/60">
                  {value !== null && (
                    <span
                      className="block h-2.5 rounded-r-[4px]"
                      style={{
                        width: `${Math.max(ratio * 100, 1.5)}%`,
                        backgroundColor: color,
                      }}
                    />
                  )}
                </span>
                <span className="tabular w-16 shrink-0 text-right text-neutral-200">
                  {value === null ? '—' : formatMoney(value)}
                </span>
              </div>

              {hovered === row.label && (
                <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 rounded bg-neutral-950/85 px-2 py-1.5 text-[11px]">
                  {row.sublabel && (
                    <Detail label="결산" value={row.sublabel} />
                  )}
                  <Detail
                    label="매출"
                    value={row.revenue === null ? '—' : formatMoney(row.revenue)}
                  />
                  <Detail
                    label="영업이익"
                    value={
                      row.operating_income === null ? '—' : formatMoney(row.operating_income)
                    }
                  />
                  <Detail
                    label="순이익"
                    value={row.net_income === null ? '—' : formatMoney(row.net_income)}
                  />
                  <Detail label="영업이익률" value={formatPct(row.operating_margin)} />
                  <Detail label="매출 증가율" value={formatDelta(row.revenue_growth)} />
                </div>
              )}
            </div>
          )
        })}
      </div>

      <dl className="grid grid-cols-3 gap-x-3 gap-y-1 border-t border-neutral-800 px-3 py-2 text-xs">
        <Stat label="영업이익률" value={formatPct(latest.operating_margin)} />
        <Stat label="ROE" value={formatPct(latest.roe)} />
        <Stat label="부채비율" value={formatPct(latest.debt_ratio)} />
      </dl>

      <div className="border-t border-neutral-800 px-3 py-1.5 text-[11px] text-neutral-600">
        {footnote}{' '}
        <a
          href={latest.source_url}
          target="_blank"
          rel="noreferrer"
          className="underline decoration-neutral-700 underline-offset-2 hover:text-neutral-400"
        >
          원문 보기
        </a>
      </div>
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-neutral-500">{label}</span>
      <span className="tabular text-neutral-300">{value}</span>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-neutral-500">{label}</dt>
      <dd className="tabular text-neutral-200">{value}</dd>
    </div>
  )
}
