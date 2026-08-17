import { useEffect, useState } from 'react'
import { fetchDailyPrices, fetchStockDetail } from '../lib/api'
import type { LiveQuote, MarketState, PricePoint, Quote } from '../lib/api'
import { PriceChart } from './PriceChart'
import { DisclosureList } from './DisclosureList'
import { FinancialSummary } from './FinancialSummary'
import { ReportAnalysis } from './ReportAnalysis'
import { SupplyDemand } from './SupplyDemand'
import {
  changeColor,
  formatBigWon,
  formatChange,
  formatRate,
  formatTimestamp,
  formatVolume,
  formatWon,
} from '../lib/format'

type Props = {
  symbol: string
  /** 목록과 같은 폴링에서 나온 현재가. 상세 화면이 따로 토스를 부르지 않는다. */
  live: LiveQuote | undefined
  market: MarketState | null
}

const CHART_DAYS = 90

export function StockDetailPanel({ symbol, live, market }: Props) {
  const [latest, setLatest] = useState<Quote | null>(null)
  const [points, setPoints] = useState<PricePoint[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.all([fetchStockDetail(symbol), fetchDailyPrices(symbol, CHART_DAYS)])
      .then(([quote, pointsResult]) => {
        if (cancelled) return
        setLatest(quote)
        setPoints(pointsResult)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    // 종목을 빠르게 바꾸면 이전 요청이 늦게 도착해 화면을 덮어쓸 수 있다. 그것을 막는다.
    return () => {
      cancelled = true
    }
  }, [symbol])

  if (loading && !latest) {
    return <div className="p-6 text-sm text-neutral-500">불러오는 중…</div>
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
        {error}
      </div>
    )
  }

  if (!latest) return null

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-xl font-semibold">{latest.name}</h2>
        <span className="tabular text-sm text-neutral-500">
          {latest.symbol} · {latest.market}
        </span>
      </div>

      {/* 현재가와 확정 종가를 나란히 둔다. 둘의 기준 시점이 다르다는 것을 화면에서 드러낸다. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <div className="flex items-center gap-1.5 text-xs text-neutral-400">
            현재가
            {market?.is_live && <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />}
          </div>
          {live ? (
            <>
              <div className="tabular mt-1 text-2xl font-semibold">
                {formatWon(Number(live.last_price))}
                <span className="ml-1 text-base font-normal text-neutral-400">원</span>
              </div>
              <div
                className={`tabular mt-1 text-sm ${
                  live.change_rate ? changeColor(live.change_rate) : 'text-neutral-500'
                }`}
              >
                {live.change !== null && live.change_rate !== null
                  ? `${formatChange(live.change)} (${formatRate(live.change_rate)})`
                  : '기준가 없음'}
              </div>
              {/* 기준가가 어느 날 종가인지 반드시 밝힌다. 확정 종가는 하루 늦게 올라오므로
                  "어제 대비"가 아니라 "그저께 대비"인 구간이 매일 생긴다. */}
              <div className="mt-2 text-xs text-neutral-500">
                {market?.label ?? ''} · 체결 {formatTimestamp(live.timestamp)}
              </div>
              {live.base_date && (
                <div className="text-xs text-neutral-500">
                  {live.base_date} 종가 {formatWon(Number(live.base_price))}원 대비
                </div>
              )}
            </>
          ) : (
            <div className="mt-2 text-sm text-neutral-500">현재가를 받는 중…</div>
          )}
        </div>

        <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <div className="text-xs text-neutral-400">확정 종가 (KRX {latest.trade_date})</div>
          <div className="tabular mt-1 text-2xl font-semibold">
            {formatWon(latest.close)}
            <span className="ml-1 text-base font-normal text-neutral-400">원</span>
          </div>
          <div className={`tabular mt-1 text-sm ${changeColor(latest.change_rate)}`}>
            {formatChange(latest.change)} ({formatRate(latest.change_rate)})
          </div>
          <div className="mt-2 text-xs text-neutral-500">
            정규장 종가 · 시간외 제외 · 현재가의 기준가
          </div>
        </div>
      </div>

      <PriceChart points={points} />

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border border-neutral-800 bg-neutral-900/40 p-4 text-sm sm:grid-cols-3">
        <Field label="시가" value={`${formatWon(latest.open)}원`} />
        <Field label="고가" value={`${formatWon(latest.high)}원`} />
        <Field label="저가" value={`${formatWon(latest.low)}원`} />
        <Field label="거래량" value={`${formatVolume(latest.volume)}주`} />
        <Field label="거래대금" value={`${formatBigWon(latest.trade_value)}원`} />
        <Field label="시가총액" value={`${formatBigWon(latest.market_cap)}원`} />
      </dl>

      {/* 수급은 시세 옆에 둔다 — 거래량·거래대금과 같은 시장 자료라서 재무보다 위가 자연스럽다. */}
      <SupplyDemand symbol={symbol} />

      <FinancialSummary symbol={symbol} />

      {/* 미국 화면과 같은 자리 — 재무표 아래, 공시 위. */}
      <ReportAnalysis symbol={symbol} />

      <DisclosureList symbol={symbol} />
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-neutral-500">{label}</dt>
      <dd className="tabular">{value}</dd>
    </div>
  )
}
