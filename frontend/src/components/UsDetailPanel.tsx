import { useEffect, useState } from 'react'
import {
  fetchUsCompany,
  fetchUsFilings,
  fetchUsFinancials,
} from '../lib/api'
import type {
  LiveQuote,
  MarketState,
  UsCompanyDetail,
  UsFilingItem,
  UsFinancialsResponse,
  UsListItem,
} from '../lib/api'
import { FinancialBars } from './FinancialBars'
import type { FinancialRow } from './FinancialBars'
import {
  changeColor,
  formatPercent,
  formatRate,
  formatTimestamp,
  formatUsd,
  formatUsdPrice,
} from '../lib/format'
import { usChangeRate, usLastPrice } from '../lib/usRate'

// 미국 종목 상세. 시세는 토스, 재무·공시는 SEC 에서 온다.
//
// ETF 는 10-K 를 내지 않으므로 재무·공시가 비는 것이 정상이다. 오류처럼 보이지 않게
// 이유를 적어 준다.

type Props = {
  symbol: string
  listItem: UsListItem | undefined
  live: LiveQuote | undefined
  market: MarketState | null
}

export function UsDetailPanel({ symbol, listItem, live, market }: Props) {
  const [company, setCompany] = useState<UsCompanyDetail | null>(null)
  const [financials, setFinancials] = useState<UsFinancialsResponse | null>(null)
  const [filings, setFilings] = useState<UsFilingItem[]>([])
  const [notes, setNotes] = useState<{ financials?: string; filings?: string }>({})
  const [loading, setLoading] = useState(true)

  // ETF·ADR 은 SEC 에 사업회사로 등록돼 있지 않아 티커로 조회하면 404 다.
  // 미리 알 수 있으므로 아예 부르지 않는다 — 실패할 요청을 세 번 보내고 오류를 보여주는 것보다
  // 왜 없는지 설명하는 편이 정확하다. (검색 결과는 구분을 모르므로 그때는 시도한다.)
  const secType = listItem?.security_type ?? null
  const hasSecFilings = secType === null || secType === 'STOCK'

  useEffect(() => {
    let cancelled = false
    setCompany(null)
    setFinancials(null)
    setFilings([])
    setNotes({})

    if (!hasSecFilings) {
      setLoading(false)
      const label = secType === 'ETF' ? 'ETF' : '주식예탁증서(DR)'
      setNotes({
        financials: `${label} 는 미국 증권거래위원회에 연차보고서(10-K)를 내지 않습니다.`,
        filings: `${label} 는 SEC 공시 대상이 아닙니다.`,
      })
      return
    }

    setLoading(true)

    // 세 호출은 서로 독립이다. 하나가 실패해도 나머지는 보여준다.
    void fetchUsCompany(symbol)
      .then((r) => !cancelled && setCompany(r))
      .catch(() => undefined)
      .finally(() => !cancelled && setLoading(false))

    void fetchUsFinancials(symbol, 6)
      .then((r) => !cancelled && setFinancials(r))
      .catch((err: Error) => {
        if (!cancelled) setNotes((n) => ({ ...n, financials: err.message }))
      })

    void fetchUsFilings(symbol, 15)
      .then((r) => !cancelled && setFilings(r))
      .catch((err: Error) => {
        if (!cancelled) setNotes((n) => ({ ...n, filings: err.message }))
      })

    return () => {
      cancelled = true
    }
  }, [symbol, hasSecFilings, secType])

  const name = company?.name ?? listItem?.name ?? symbol
  const price = usLastPrice(listItem, live)
  const rate = usChangeRate(listItem, live)

  const rows: FinancialRow[] = (financials?.years ?? []).map((year) => ({
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

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-xl font-semibold">{name}</h2>
          <span className="tabular text-sm text-neutral-500">
            {symbol}
            {company?.exchange ? ` · ${company.exchange}` : ''}
          </span>
        </div>
        {company?.industry && (
          <p className="mt-0.5 text-xs text-neutral-500">{company.industry}</p>
        )}
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
        <div className="flex items-center gap-1.5 text-xs text-neutral-400">
          현재가
          {market?.is_live && (
            <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
          )}
        </div>
        {price !== undefined ? (
          <>
            <div className="tabular mt-1 text-2xl font-semibold">{formatUsdPrice(price)}</div>
            <div className={`tabular mt-1 text-sm ${rate ? changeColor(rate) : 'text-neutral-500'}`}>
              {rate !== null ? formatRate(rate) : '—'}
            </div>
            <div className="mt-2 text-xs text-neutral-500">
              {market?.label ?? ''}
              {live?.timestamp ? ` · 체결 ${formatTimestamp(live.timestamp)}` : ''}
            </div>
          </>
        ) : (
          <div className="mt-2 text-sm text-neutral-500">현재가를 받는 중…</div>
        )}
      </div>

      {rows.length > 0 ? (
        <FinancialBars
          rows={rows}
          formatMoney={formatUsd}
          formatPct={(v) => (v === null ? '—' : formatPercent(v))}
          formatDelta={(v) => (v === null ? '—' : formatRate(v))}
          badge="10-K"
          footnote={`FY${rows[rows.length - 1].label} 연차보고서 기준 ·`}
        />
      ) : (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 px-3 py-4 text-xs text-neutral-500">
          {notes.financials ?? (loading ? '재무 데이터를 받는 중…' : '재무 데이터가 없습니다.')}
        </div>
      )}

      <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
        <div className="border-b border-neutral-800 px-3 py-2 text-xs text-neutral-400">
          공시 <span className="text-neutral-600">10-K 연차 · 10-Q 분기 · 8-K 수시</span>
        </div>
        {filings.length === 0 ? (
          <p className="px-3 py-4 text-xs text-neutral-500">
            {notes.filings ?? (loading ? '불러오는 중…' : '표시할 공시가 없습니다.')}
          </p>
        ) : (
          <ul className="max-h-64 divide-y divide-neutral-800/70 overflow-y-auto">
            {filings.map((filing) => (
              <li key={filing.accession_no}>
                {/* EDGAR 원문으로 나가는 링크다. 외부 사이트이므로 새 탭에서 연다. */}
                <a
                  href={filing.viewer_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-baseline gap-3 px-3 py-2 text-sm transition-colors hover:bg-neutral-800/60"
                >
                  <span className="tabular shrink-0 text-xs text-neutral-500">
                    {filing.filing_date.slice(2).replace(/-/g, '.')}
                  </span>
                  <span className="w-14 shrink-0 text-neutral-300">{filing.form}</span>
                  <span className="min-w-0 flex-1 truncate text-xs text-neutral-500">
                    {filing.report_date ? `기준 ${filing.report_date}` : filing.description}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
