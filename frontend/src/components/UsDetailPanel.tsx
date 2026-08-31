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
import { SECTION_OPTIONS, type Section } from '../lib/useRoute'
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
import { Card } from './ui/Card'
import { Segmented } from './ui/Segmented'
import { Skeleton } from './ui/Skeleton'
import { Empty } from './ui/Status'

// 미국 종목 상세. 시세는 토스, 재무·공시는 SEC 에서 온다.
//
// **국내(`StockDetailPanel`)와 같은 뼈대다** — 이름·현재가는 늘 위에 있고, 그 아래가
// 개요/재무/공시·분석 세 묶음으로 갈린다. 담기는 값은 다르다(차트·수급·확정 종가가 없고,
// 대신 SEC 기업 정보가 있다). 그래도 구조가 같아야 탭을 옮길 때 규칙을 다시 익히지 않는다.
//
// ETF 는 10-K 를 내지 않으므로 재무·공시가 비는 것이 정상이다. 오류처럼 보이지 않게
// 이유를 적어 준다.

type Props = {
  symbol: string
  listItem: UsListItem | undefined
  live: LiveQuote | undefined
  market: MarketState | null
  section: Section
  onSection: (next: Section) => void
}

export function UsDetailPanel({ symbol, listItem, live, market, section, onSection }: Props) {
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
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-xl font-semibold">{name}</h2>
        <WatchStar symbol={symbol} />
        <span className="tabular text-sm text-neutral-500">
          {symbol}
          {company?.exchange ? ` · ${company.exchange}` : ''}
        </span>
      </div>

      <Card
        title={
          <span className="inline-flex items-center gap-1.5">
            현재가
            {market?.is_live && (
              <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
            )}
          </span>
        }
        bodyClassName="px-3 py-3"
      >
        {price !== undefined ? (
          <>
            <div className="tabular text-2xl font-semibold">{formatUsdPrice(price)}</div>
            <div className={`tabular mt-1 text-sm ${rate ? changeColor(rate) : 'text-neutral-500'}`}>
              {rate !== null ? formatRate(rate) : '—'}
            </div>
            <div className="mt-2 text-xs text-neutral-500">
              {market?.label ?? ''}
              {live?.timestamp ? ` · 체결 ${formatTimestamp(live.timestamp)}` : ''}
            </div>
          </>
        ) : (
          <Skeleton rows={3} label="현재가를 받는 중…" />
        )}
      </Card>

      <Segmented
        size="md"
        label="상세 섹션"
        options={SECTION_OPTIONS}
        value={section}
        onChange={onSection}
      />

      {section === 'overview' && (
        <>
          {/* 국내의 개요에는 차트·시세·수급이 들어가는데 미국에는 그만한 시장 자료가 없다.
              대신 SEC 가 아는 회사 정보를 여기 둔다 — 지금까지는 제목 옆에 업종 한 줄만
              끼워 넣고 나머지(CIK·결산월·홈페이지)는 화면에 아예 없었다. */}
          <Card title="기업 정보" hint="SEC 등록 정보" bodyClassName="px-3 py-3">
            {company ? (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <Field label="업종" value={company.industry ?? '—'} wide />
                <Field label="거래소" value={company.exchange ?? '—'} />
                {/* 결산월은 재무를 읽을 때 필요하다. 애플의 2025 회계연도는 9월에 끝난다. */}
                <Field label="결산" value={formatFiscalEnd(company.fiscal_year_end)} />
                <Field label="CIK" value={company.cik} />
                {company.website && (
                  <div className="col-span-2">
                    <dt className="text-xs text-neutral-500">홈페이지</dt>
                    <dd className="truncate">
                      <a
                        href={company.website}
                        target="_blank"
                        rel="noreferrer"
                        className="text-neutral-300 underline decoration-neutral-700 underline-offset-2 hover:text-neutral-100"
                      >
                        {company.website.replace(/^https?:\/\//, '')}
                      </a>
                    </dd>
                  </div>
                )}
              </dl>
            ) : loading ? (
              <Skeleton rows={4} label="기업 정보를 받는 중…" />
            ) : (
              <Empty
                title="SEC 에 등록된 기업 정보가 없습니다."
                hint={
                  hasSecFilings
                    ? '티커로 회사를 찾지 못했습니다.'
                    : 'ETF·DR 은 사업회사로 등록되지 않습니다.'
                }
              />
            )}
          </Card>

          {/* 국내와 같은 자리 — 개요 맨 아래. 눌러 들어가야 하면 안 쓰게 된다. */}
          <StockNotes symbol={symbol} />
        </>
      )}

      {section === 'finance' && (
        <>
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
            fallback={notes.financials ?? null}
            loading={loading && financials === null && notes.financials === undefined}
          />
        </>
      )}

      {section === 'filings' && (
        <>
          {/* 10-K 를 내는 종목에만 붙인다. ETF·DR 은 애초에 분석할 문서가 없다. */}
          {hasSecFilings && <TenKAnalysis ticker={symbol} />}

          <Card title="공시" hint="10-K 연차 · 10-Q 분기 · 8-K 수시" bodyClassName="">
            {filings.length > 0 ? (
              <ul className="max-h-96 divide-y divide-neutral-800/70 overflow-y-auto">
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
            ) : loading ? (
              <Skeleton rows={6} label="공시를 받는 중…" className="px-3 py-3" />
            ) : (
              <Empty title={notes.filings ?? '표시할 공시가 없습니다.'} className="px-3 py-3" />
            )}
          </Card>
        </>
      )}
    </div>
  )
}

function Field({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? 'col-span-2' : undefined}>
      <dt className="text-xs text-neutral-500">{label}</dt>
      <dd className="text-neutral-200">{value}</dd>
    </div>
  )
}

/** SEC 는 결산일을 MMDD 네 자리로 준다. 0930 → 9월 30일 */
function formatFiscalEnd(raw: string | null): string {
  if (!raw || raw.length !== 4) return raw ?? '—'
  return `${Number(raw.slice(0, 2))}월 ${Number(raw.slice(2))}일`
}
