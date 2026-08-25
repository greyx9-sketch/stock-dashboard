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
import { UsValuationBox } from './UsValuationBox'
import { UsFinancialPeriod } from './UsFinancialPeriod'
import { UsPeerComparison } from './UsPeerComparison'
import { TenKAnalysis } from './TenKAnalysis'
import { StockNotes } from './StockNotes'
import { WatchStar } from './WatchStar'
import {
  changeColor,
  formatRate,
  formatTimestamp,
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

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-xl font-semibold">{name}</h2>
          <WatchStar symbol={symbol} />
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

      {/* 국내 화면과 같은 자리 — 재무 위. 아래로 밀면 긴 분석을 지나쳐야 해서 안 쓰게 된다. */}
      <StockNotes symbol={symbol} />

      {/* 지표를 재무표 위에 둔다. 국내 화면과 같은 순서다 — PER·PBR 을 먼저 보고
          그 근거인 추이로 내려간다. */}
      <UsValuationBox ticker={symbol} />

      {/* 지표 바로 아래. 국내 화면과 같은 순서다 — "이 회사 PER 이 42배"를 보고
          "업종은 어떤가"로 이어진다. 업종을 모르면 아무것도 그리지 않는다. */}
      <UsPeerComparison ticker={symbol} />

      {/* 연간/분기 전환은 이 안에 있다. 연간은 위에서 이미 받아 두었으므로 넘겨주고,
          분기는 처음 누를 때만 따로 받는다. */}
      <UsFinancialPeriod
        ticker={symbol}
        annual={financials}
        fallback={notes.financials ?? (loading ? '재무 데이터를 받는 중…' : '재무 데이터가 없습니다.')}
      />

      {/* 10-K 를 내는 종목에만 붙인다. ETF·DR 은 애초에 분석할 문서가 없다. */}
      {hasSecFilings && <TenKAnalysis ticker={symbol} />}

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
