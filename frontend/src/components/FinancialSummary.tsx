import { useEffect, useState } from 'react'
import { fetchFinancials, fetchQuarterlyFinancials } from '../lib/api'
import type { FinancialsResponse, QuarterlyResponse } from '../lib/api'
import { FinancialBars } from './FinancialBars'
import type { FinancialRow } from './FinancialBars'
import { formatBigWon, formatPercent, formatRate } from '../lib/format'

// 국내 재무(OpenDART). 받아 온 응답을 공통 표시 형태로 옮기는 일만 한다.
//
// 기간을 두 갈래로 본다:
//
//   연간 — 사업보고서 기준. 오래 보던 화면 그대로다.
//   분기 — 3개월치와 누적을 **전환해서** 본다. 둘 다 보고서에 적힌 원값이라
//          어느 쪽을 골라도 계산한 숫자가 아니다(4분기만 예외).
//
// 분기를 처음 열 때만 부른다. 종목 상세를 열 때마다 열 번 넘게 OpenDART 를 부르면
// 느리기도 하고 rate limit 도 아깝다.

type Props = {
  symbol: string
}

type Period = 'annual' | 'quarterly'
/** 분기를 볼 때의 기준. 3개월치인가 연초부터 누적인가. */
type Basis = 'quarter' | 'cumulative'

export function FinancialSummary({ symbol }: Props) {
  const [period, setPeriod] = useState<Period>('annual')
  const [basis, setBasis] = useState<Basis>('quarter')

  const [annual, setAnnual] = useState<FinancialsResponse | null>(null)
  const [quarterly, setQuarterly] = useState<QuarterlyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // 종목이 바뀌면 전부 비운다. 앞 종목의 숫자가 잠깐이라도 남아 있으면 안 된다.
  useEffect(() => {
    setAnnual(null)
    setQuarterly(null)
    setPeriod('annual')
  }, [symbol])

  useEffect(() => {
    // 이미 받아 둔 것이면 다시 부르지 않는다.
    if (period === 'annual' && annual) return
    if (period === 'quarterly' && quarterly) return

    let cancelled = false
    setLoading(true)
    setError(null)

    const request =
      period === 'annual'
        ? fetchFinancials(symbol, 6).then((r) => {
            if (!cancelled) setAnnual(r)
          })
        : fetchQuarterlyFinancials(symbol, 12).then((r) => {
            if (!cancelled) setQuarterly(r)
          })

    request
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [symbol, period, annual, quarterly])

  const data = period === 'annual' ? annual : quarterly
  const empty =
    period === 'annual'
      ? !annual || annual.years.length === 0
      : !quarterly || quarterly.quarters.length === 0

  const switcher = (
    <PeriodSwitch period={period} onChange={setPeriod} />
  )

  if (loading && !data) {
    return (
      <Shell switcher={switcher}>
        {period === 'annual'
          ? '재무 데이터를 받는 중… (처음 보는 종목은 몇 초 걸립니다)'
          : '분기 데이터를 받는 중… (처음 보는 종목은 십여 초 걸립니다)'}
      </Shell>
    )
  }

  if (error || empty) {
    return <Shell switcher={switcher}>{error ?? '재무 데이터가 없습니다.'}</Shell>
  }

  const money = (v: number) => `${formatBigWon(v)}원`
  const pct = (v: string | null) => (v === null ? '—' : formatPercent(v))
  const delta = (v: string | null) => (v === null ? '—' : formatRate(v))

  if (period === 'annual' && annual) {
    const rows: FinancialRow[] = annual.years.map((year) => ({
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
    const latestYear = annual.years[annual.years.length - 1].fiscal_year

    return (
      <FinancialBars
        rows={rows}
        formatMoney={money}
        formatPct={pct}
        formatDelta={delta}
        title="재무"
        extraControls={switcher}
        badge={annual.fs_label}
        footnote={`${latestYear} 사업보고서 기준 ·`}
      />
    )
  }

  if (!quarterly) return null

  const cumulative = basis === 'cumulative'
  const rows: FinancialRow[] = quarterly.quarters.map((q) => ({
    // "2025 3Q" 는 폭을 많이 먹는다. 표에서는 연도를 두 자리로 줄인다.
    label: `${String(q.fiscal_year).slice(2)} ${q.quarter}Q`,
    // 4분기의 3개월 손익만 계산값이다. 누적으로 보고 있을 때는 사업보고서 원값이라
    // 표시를 붙이지 않는다 — 안 붙는 것이 맞는 자리에 붙이면 표시가 뜻을 잃는다.
    note:
      q.derived && !cumulative
        ? 'DART 에 4분기 보고서가 없어 연간에서 3분기 누적을 뺀 값입니다'
        : undefined,
    revenue: cumulative ? q.revenue_cum : q.revenue,
    operating_income: cumulative ? q.operating_income_cum : q.operating_income,
    net_income: cumulative ? q.net_income_cum : q.net_income,
    total_assets: q.total_assets,
    operating_margin: cumulative ? q.operating_margin_cum : q.operating_margin,
    revenue_growth: cumulative ? q.revenue_cum_yoy : q.revenue_yoy,
    // ROE 는 내지 않는다. 순이익은 3개월치인데 자본은 잔액이라 둘을 나누면 연간과
    // 견줄 수 없는 숫자가 된다. 빈 값은 아래 지표 줄에서 자리째 빠진다.
    roe: null,
    debt_ratio: q.debt_ratio,
    source_url: q.source_url,
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
      badge={quarterly.fs_label}
      footnote={
        `${last.label} 기준 · 증가율은 전년 동분기 대비` +
        // 별표가 붙은 행이 있을 때만 그 뜻을 적는다. 없는데 적으면 무엇을 찾으라는 건지
        // 알 수 없는 설명이 된다.
        (rows.some((r) => r.note) ? ' · *는 연간에서 3분기 누적을 뺀 값' : '') +
        ' ·'
      }
    />
  )
}

/** 연간 ↔ 분기. */
function PeriodSwitch({
  period,
  onChange,
}: {
  period: Period
  onChange: (next: Period) => void
}) {
  return (
    <span className="mr-1 flex overflow-hidden rounded border border-neutral-800">
      {(
        [
          ['annual', '연간'],
          ['quarterly', '분기'],
        ] as const
      ).map(([key, label]) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={`px-1.5 py-0.5 text-[11px] transition-colors ${
            period === key
              ? 'bg-neutral-700 text-neutral-100'
              : 'text-neutral-500 hover:bg-neutral-800'
          }`}
        >
          {label}
        </button>
      ))}
    </span>
  )
}

/** 3개월 ↔ 누적. 분기를 볼 때만 나온다. */
function BasisSwitch({
  basis,
  onChange,
}: {
  basis: Basis
  onChange: (next: Basis) => void
}) {
  return (
    <span
      className="mr-1 flex overflow-hidden rounded border border-neutral-800"
      title="3개월: 그 분기만 / 누적: 연초부터 그 분기까지"
    >
      {(
        [
          ['quarter', '3개월'],
          ['cumulative', '누적'],
        ] as const
      ).map(([key, label]) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={`px-1.5 py-0.5 text-[11px] transition-colors ${
            basis === key
              ? 'bg-neutral-700 text-neutral-100'
              : 'text-neutral-500 hover:bg-neutral-800'
          }`}
        >
          {label}
        </button>
      ))}
    </span>
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
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div className="flex flex-wrap items-center gap-1 border-b border-neutral-800 px-3 py-2">
        <span className="mr-1 text-xs text-neutral-400">재무</span>
        {switcher}
      </div>
      <div className="px-3 py-4 text-xs text-neutral-500">{children}</div>
    </div>
  )
}
