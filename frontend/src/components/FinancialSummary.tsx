import { useEffect, useMemo, useState } from 'react'
import { fetchFinancials } from '../lib/api'
import type { FinancialYear, FinancialsResponse } from '../lib/api'
import { formatBigWon, formatPercent, formatRate } from '../lib/format'

// 연간 재무 추이.
//
// 형태 선택: 값 하나를 연도(순서형 축)에 걸쳐 비교하는 일이라 막대가 맞다. 다만 패널이
// 좁아서 세로 막대 대신 **막대가 들어간 표**로 만들었다 — 연도·막대·수치가 한 줄에 놓여
// 6개 연도가 전부 보이고, 표 자체가 곧 데이터 테이블 역할을 한다.
//
// 축은 하나만 쓴다. 영업이익률을 같은 그림에 두 번째 축으로 겹치지 않고 옆의 숫자로 적는다.
// (서로 다른 단위를 한 그림에 겹치면 두 선의 교차가 아무 뜻도 없는 그림이 된다.)
//
// 색: 매출은 크기만 나타내므로 중립색. 이익은 부호가 뜻을 가지므로 국내 관례대로
// 흑자 빨강 / 적자 파랑. 두 색은 색각 이상 시뮬레이션에서 충분히 구분된다(ΔE 25).

type MetricKey = 'revenue' | 'operating_income' | 'net_income'

const METRICS: { key: MetricKey; label: string; polar: boolean }[] = [
  { key: 'revenue', label: '매출', polar: false },
  { key: 'operating_income', label: '영업이익', polar: true },
  { key: 'net_income', label: '순이익', polar: true },
]

type Props = {
  symbol: string
}

export function FinancialSummary({ symbol }: Props) {
  const [data, setData] = useState<FinancialsResponse | null>(null)
  const [metric, setMetric] = useState<MetricKey>('revenue')
  const [hovered, setHovered] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchFinancials(symbol, 6)
      .then((result) => {
        if (cancelled) return
        setData(result)
        // 금융지주처럼 매출액 계정이 없는 회사는 매출 막대가 전부 비어 버린다.
        // 그런 경우 영업이익으로 바꿔서 보여준다.
        const hasRevenue = result.years.some((y) => y.revenue !== null)
        setMetric(hasRevenue ? 'revenue' : 'operating_income')
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message)
          setData(null)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [symbol])

  const years = data?.years ?? []
  const active = METRICS.find((m) => m.key === metric) ?? METRICS[0]

  // 막대 길이는 절댓값의 최댓값을 기준으로 잡는다. 적자가 섞여 있어도 크기 비교가 된다.
  const scale = useMemo(() => {
    const values = years.map((y) => Math.abs(y[metric] ?? 0))
    return Math.max(...values, 1)
  }, [years, metric])

  if (loading && !data) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 px-3 py-4 text-xs text-neutral-500">
        재무 데이터를 받는 중… (처음 보는 종목은 몇 초 걸립니다)
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 px-3 py-4 text-xs text-neutral-500">
        {error}
      </div>
    )
  }

  if (!data || years.length === 0) return null

  const latest = years[years.length - 1]

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
        <span className="ml-auto text-xs text-neutral-600">{data.fs_label}</span>
      </div>

      <div className="px-3 py-2">
        {years.map((year) => {
          const value = year[metric]
          const ratio = value === null ? 0 : Math.abs(value) / scale
          const negative = (value ?? 0) < 0
          // 크기만 나타내는 값은 중립색, 부호가 뜻을 갖는 값은 흑자/적자 색을 쓴다.
          const color = !active.polar
            ? 'var(--color-bar)'
            : negative
              ? 'var(--color-down)'
              : 'var(--color-up)'

          return (
            <div
              key={year.fiscal_year}
              onMouseEnter={() => setHovered(year.fiscal_year)}
              onMouseLeave={() => setHovered(null)}
              className="relative -mx-1 rounded px-1 py-1 transition-colors hover:bg-neutral-800/50"
            >
              <div className="flex items-baseline gap-2 text-xs">
                <span className="tabular w-9 shrink-0 text-neutral-500">
                  {year.fiscal_year}
                </span>
                {/* 막대는 기준선에 붙고 끝만 둥글다. 값이 없으면 막대를 그리지 않는다. */}
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
                <span className="tabular w-14 shrink-0 text-right text-neutral-200">
                  {value === null ? '—' : `${formatBigWon(value)}원`}
                </span>
              </div>

              {hovered === year.fiscal_year && (
                <YearDetail year={year} />
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
        {latest.fiscal_year} 사업보고서 기준 ·{' '}
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

/** 막대에 마우스를 올렸을 때 그 해의 세부 수치. */
function YearDetail({ year }: { year: FinancialYear }) {
  const items: [string, string][] = [
    ['매출', year.revenue === null ? '—' : `${formatBigWon(year.revenue)}원`],
    ['영업이익', year.operating_income === null ? '—' : `${formatBigWon(year.operating_income)}원`],
    ['순이익', year.net_income === null ? '—' : `${formatBigWon(year.net_income)}원`],
    ['영업이익률', formatPct(year.operating_margin)],
    ['매출 증가율', formatDelta(year.revenue_growth)],
    ['자산총계', year.total_assets === null ? '—' : `${formatBigWon(year.total_assets)}원`],
  ]

  return (
    <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 rounded bg-neutral-950/80 px-2 py-1.5 text-[11px]">
      {items.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-2">
          <span className="text-neutral-500">{label}</span>
          <span className="tabular text-neutral-300">{value}</span>
        </div>
      ))}
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

/** 수준을 나타내는 비율(마진·ROE·부채비율)은 부호를 붙이지 않는다. */
function formatPct(value: string | null): string {
  return value === null ? '—' : formatPercent(value)
}

/** 변화를 나타내는 비율(증가율)은 부호를 붙인다. */
function formatDelta(value: string | null): string {
  return value === null ? '—' : formatRate(value)
}
