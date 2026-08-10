import { useEffect, useState } from 'react'
import { fetchDailyPrices, fetchStockDetail } from '../lib/api'
import type { PricePoint, StockDetail } from '../lib/api'
import { PriceChart } from './PriceChart'
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
}

const CHART_DAYS = 90

export function StockDetailPanel({ symbol }: Props) {
  const [detail, setDetail] = useState<StockDetail | null>(null)
  const [points, setPoints] = useState<PricePoint[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.all([fetchStockDetail(symbol), fetchDailyPrices(symbol, CHART_DAYS)])
      .then(([detailResult, pointsResult]) => {
        if (cancelled) return
        setDetail(detailResult)
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

  if (loading && !detail) {
    return <div className="p-6 text-sm text-neutral-500">불러오는 중…</div>
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
        {error}
      </div>
    )
  }

  if (!detail) return null

  const { latest, live, live_error } = detail

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-xl font-semibold">{latest.name}</h2>
          <span className="tabular text-sm text-neutral-500">
            {latest.symbol} · {latest.market}
          </span>
        </div>
      </div>

      {/* 현재가와 확정 종가를 나란히 둔다. 둘의 기준 시점이 다르다는 것을 화면에서 드러내는 게 중요하다. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <div className="text-xs text-neutral-400">현재가 (토스증권)</div>
          {live ? (
            <>
              <div className="tabular mt-1 text-2xl font-semibold">
                {formatWon(Number(live.last_price))}
                <span className="ml-1 text-base font-normal text-neutral-400">원</span>
              </div>
              <div className={`tabular mt-1 text-sm ${changeColor(live.change_rate)}`}>
                {formatChange(live.change)} ({formatRate(live.change_rate)})
              </div>
              <div className="mt-2 text-xs text-neutral-500">
                기준가 {formatWon(Number(live.base_price))}원 · {formatTimestamp(live.timestamp)}
              </div>
            </>
          ) : (
            <div className="mt-2 text-sm text-neutral-500">
              {live_error ?? '현재가를 가져오지 못했습니다.'}
            </div>
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
          <div className="mt-2 text-xs text-neutral-500">정규장 종가 · 시간외 제외</div>
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
