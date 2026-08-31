import { useEffect, useState } from 'react'
import { fetchUsQuarterly, type UsFinancialsResponse, type UsQuarterly } from '../lib/api'
import { FinancialBars } from './FinancialBars'
import type { FinancialRow } from './FinancialBars'
import { formatPercent, formatRate, formatUsd } from '../lib/format'
import { Card } from './ui/Card'
import { Segmented } from './ui/Segmented'
import { Skeleton } from './ui/Skeleton'

// 미국 재무의 연간/분기 전환. 국내(`FinancialSummary`)와 같은 짜임이다.
//
// **연간은 부모가 이미 받아 두었다.** 종목을 열 때 상세 정보와 함께 받으므로 여기서
// 다시 부르지 않는다. 분기만 이 안에서 받는다 — 분기를 처음 누를 때 한 번이다.
//
// 국내와 다른 것 하나: **회계연도가 회사마다 달라 분기 종료일을 함께 보여준다.**
// 애플 FY2026 1분기는 2025년 12월에 끝나고 마이크로소프트는 2025년 9월에 끝난다.
// "FY2026 1Q" 만 적으면 그게 언제인지 알 수 없다.

type Props = {
  ticker: string
  annual: UsFinancialsResponse | null
  /** 연간이 비어 있을 때 대신 적을 이유. ETF 라서 없는 것과 못 받은 것을 구분한다. */
  fallback: string | null
  /** 부모가 아직 연간을 받는 중인가. 없는 것과 아직 안 온 것은 달라 보여야 한다. */
  loading?: boolean
}

type Period = 'annual' | 'quarterly'
type Basis = 'quarter' | 'cumulative'

export function UsFinancialPeriod({ ticker, annual, fallback, loading: pending = false }: Props) {
  const [period, setPeriod] = useState<Period>('annual')
  const [basis, setBasis] = useState<Basis>('quarter')
  const [quarterly, setQuarterly] = useState<UsQuarterly | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // 종목이 바뀌면 비운다. 앞 종목의 숫자가 잠깐이라도 남으면 안 된다.
  useEffect(() => {
    setQuarterly(null)
    setPeriod('annual')
  }, [ticker])

  useEffect(() => {
    if (period !== 'quarterly' || quarterly) return

    let cancelled = false
    setLoading(true)
    setError(null)

    fetchUsQuarterly(ticker, 12)
      .then((result) => {
        if (!cancelled) setQuarterly(result)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [ticker, period, quarterly])

  const switcher = <PeriodSwitch period={period} onChange={setPeriod} />
  const money = (v: number) => formatUsd(v)
  const pct = (v: string | null) => (v === null ? '—' : formatPercent(v))
  const delta = (v: string | null) => (v === null ? '—' : formatRate(v))

  if (period === 'annual') {
    const rows: FinancialRow[] = (annual?.years ?? []).map((year) => ({
      label: String(year.fiscal_year),
      sublabel: year.period_end,
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

    if (rows.length === 0) {
      return (
        <Shell switcher={switcher}>
          {pending ? (
            <Skeleton rows={6} label="재무를 받는 중…" />
          ) : (
            (fallback ?? '재무 데이터가 없습니다.')
          )}
        </Shell>
      )
    }

    return (
      <FinancialBars
        rows={rows}
        formatMoney={money}
        formatPct={pct}
        formatDelta={delta}
        title="재무"
        extraControls={switcher}
        badge="10-K"
        footnote={`FY${rows[rows.length - 1].label} 연차보고서 기준 ·`}
      />
    )
  }

  if (loading && !quarterly) {
    return (
      <Shell switcher={switcher}>
        <Skeleton rows={6} label="분기 데이터를 받는 중… (처음 보는 종목은 몇 초 걸립니다)" />
      </Shell>
    )
  }
  if (error || !quarterly || quarterly.quarters.length === 0) {
    return <Shell switcher={switcher}>{error ?? '분기 데이터가 없습니다.'}</Shell>
  }

  const cumulative = basis === 'cumulative'
  const rows: FinancialRow[] = quarterly.quarters.map((q) => ({
    label: `${String(q.fiscal_year).slice(2)} ${q.quarter}Q`,
    // 회계연도가 회사마다 다르다. 종료일이 없으면 "FY2026 1Q" 가 언제인지 알 수 없다.
    sublabel: q.period_end ?? undefined,
    // 4분기의 3개월 손익만 계산값이다. 누적으로 볼 때는 10-K 원값이라 표시하지 않는다.
    note:
      q.derived && !cumulative
        ? '10-Q 가 없는 분기라 10-K 에서 3분기 누적을 뺀 값입니다'
        : undefined,
    revenue: cumulative ? q.revenue_cum : q.revenue,
    operating_income: cumulative ? q.operating_income_cum : q.operating_income,
    net_income: cumulative ? q.net_income_cum : q.net_income,
    total_assets: q.total_assets,
    operating_margin: cumulative ? q.operating_margin_cum : q.operating_margin,
    revenue_growth: cumulative ? q.revenue_cum_yoy : q.revenue_yoy,
    // 분기 ROE 는 내지 않는다 — 순이익은 3개월치인데 자본은 잔액이라 연간과 견줄 수 없다.
    roe: null,
    debt_ratio: null,
    source_url: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${quarterly.cik}&type=10-Q`,
  }))

  const last = quarterly.quarters[quarterly.quarters.length - 1]

  return (
    <FinancialBars
      rows={rows}
      formatMoney={money}
      formatPct={pct}
      formatDelta={delta}
      title="재무"
      extraControls={
        <>
          {switcher}
          <BasisSwitch basis={basis} onChange={setBasis} />
        </>
      }
      badge="10-Q"
      footnote={
        `${last.label} (${last.period_end}) 기준 · 증가율은 전년 동분기 대비` +
        (rows.some((r) => r.note) ? ' · *는 10-K 에서 3분기 누적을 뺀 값' : '') +
        ' ·'
      }
    />
  )
}

function PeriodSwitch({ period, onChange }: { period: Period; onChange: (next: Period) => void }) {
  return (
    <Segmented
      grouped
      className="mr-1"
      label="재무 기간"
      options={[
        { value: 'annual', label: '연간' },
        { value: 'quarterly', label: '분기' },
      ] as const}
      value={period}
      onChange={onChange}
    />
  )
}

function BasisSwitch({ basis, onChange }: { basis: Basis; onChange: (next: Basis) => void }) {
  return (
    <Segmented
      grouped
      className="mr-1"
      label="분기 집계 기준"
      title="3개월: 그 분기만 / 누적: 회계연도 초부터 그 분기까지"
      options={[
        { value: 'quarter', label: '3개월' },
        { value: 'cumulative', label: '누적' },
      ] as const}
      value={basis}
      onChange={onChange}
    />
  )
}

/** 데이터가 없을 때도 기간 전환은 살아 있어야 한다 — 분기가 없다고 연간까지 막히면 안 된다. */
function Shell({
  switcher,
  children,
}: {
  switcher: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Card title="재무" actions={switcher} bodyClassName="px-3 py-4 text-xs text-neutral-500">
      {children}
    </Card>
  )
}
