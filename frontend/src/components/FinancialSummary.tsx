import { useEffect, useState } from 'react'
import { fetchFinancials } from '../lib/api'
import type { FinancialsResponse } from '../lib/api'
import { FinancialBars } from './FinancialBars'
import type { FinancialRow } from './FinancialBars'
import { formatBigWon, formatPercent, formatRate } from '../lib/format'

// 국내 재무(OpenDART). 받아 온 응답을 공통 표시 형태로 옮기는 일만 한다.

type Props = {
  symbol: string
}

export function FinancialSummary({ symbol }: Props) {
  const [data, setData] = useState<FinancialsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchFinancials(symbol, 6)
      .then((result) => {
        if (!cancelled) setData(result)
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

  if (loading && !data) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 px-3 py-4 text-xs text-neutral-500">
        재무 데이터를 받는 중… (처음 보는 종목은 몇 초 걸립니다)
      </div>
    )
  }

  if (error || !data || data.years.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 px-3 py-4 text-xs text-neutral-500">
        {error ?? '재무 데이터가 없습니다.'}
      </div>
    )
  }

  const rows: FinancialRow[] = data.years.map((year) => ({
    label: String(year.fiscal_year),
    revenue: year.revenue,
    operating_income: year.operating_income,
    net_income: year.net_income,
    total_assets: year.total_assets,
    operating_margin: year.operating_margin,
    revenue_growth: year.revenue_growth,
    roe: year.roe,
    debt_ratio: year.debt_ratio,
    source_url: year.source_url,
  }))

  const latestYear = data.years[data.years.length - 1].fiscal_year

  return (
    <FinancialBars
      rows={rows}
      formatMoney={(v) => `${formatBigWon(v)}원`}
      formatPct={(v) => (v === null ? '—' : formatPercent(v))}
      formatDelta={(v) => (v === null ? '—' : formatRate(v))}
      badge={data.fs_label}
      footnote={`${latestYear} 사업보고서 기준 ·`}
    />
  )
}
