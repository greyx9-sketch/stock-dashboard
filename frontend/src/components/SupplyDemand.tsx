import { useEffect, useState } from 'react'
import { fetchFlows } from '../lib/api'
import type { FlowMetric, Flows, InvestorDay } from '../lib/api'
import { changeColor, formatShortDate } from '../lib/format'

// 수급 동향 블록 (국내 전용).
//
// 다섯 자료를 그대로 늘어놓지 않는다. 종목 상세는 이미 길고, 원자료를 나열하면 읽히지
// 않는다. 실무자가 보는 순서로 압축했다 — 투자자별 순매수를 표로, 나머지 넷은 지표 한 줄로.
//
// **지표마다 기준일이 다를 수 있다.** 공매도·대차거래는 당일 18~19시, 신용거래·투자자별은
// 다음 영업일 04시에 갱신된다. 하나의 날짜로 뭉뚱그리면 없는 자료를 있는 것처럼 보이게 되므로
// 항목마다 기준일을 따로 보여준다.

type Props = {
  symbol: string
}

const DAYS = 5

export function SupplyDemand({ symbol }: Props) {
  const [flows, setFlows] = useState<Flows | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setFlows(null)
    setError(null)
    setLoading(true)

    void fetchFlows(symbol, DAYS)
      .then((r) => !cancelled && setFlows(r))
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))

    return () => {
      cancelled = true
    }
  }, [symbol])

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div className="border-b border-neutral-800 px-3 py-2 text-xs text-neutral-400">
        수급 <span className="text-neutral-600">투자자별 · 공매도 · 신용 · 대차</span>
      </div>

      <div className="px-3 py-3">
        {loading && <p className="text-xs text-neutral-500">불러오는 중…</p>}

        {!loading && error && (
          <p className="whitespace-pre-line text-xs text-neutral-500">{error}</p>
        )}

        {!loading && !error && flows && (
          <div className="space-y-3">
            {flows.investors.length > 0 && <InvestorTable days={flows.investors} />}

            {flows.metrics.length > 0 && (
              <dl className="grid grid-cols-2 gap-x-3 gap-y-2 border-t border-neutral-800 pt-2.5">
                {flows.metrics.map((metric) => (
                  <div key={metric.label}>
                    <dt className="text-[11px] text-neutral-500">{metric.label}</dt>
                    <dd className="tabular text-sm text-neutral-200">
                      {metric.value}
                      {metric.unit && (
                        <span className="ml-0.5 text-[11px] text-neutral-500">{metric.unit}</span>
                      )}
                    </dd>
                    {/* 기준일을 항목마다 적는다 — 자료별로 갱신 시각이 다르다. */}
                    <dd className="text-[10px] text-neutral-600">{caption(metric)}</dd>
                  </div>
                ))}
              </dl>
            )}

            {/* 일부만 못 받은 경우. 전체를 감추지 않고 무엇이 빠졌는지만 알린다. */}
            {flows.errors.length > 0 && (
              <p className="border-t border-neutral-800 pt-2 text-[10px] text-neutral-600">
                일부 자료를 받지 못했습니다 ({flows.errors.length}건). 갱신 전일 수 있습니다.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/** "8/14 (금) · 거래량 기준". 기준일이나 설명이 없는 지표도 있어 빈 조각은 뺀다. */
function caption(metric: FlowMetric): string {
  const parts = [metric.as_of ? formatShortDate(metric.as_of) : '', metric.note]
  return parts.filter(Boolean).join(' · ')
}

function InvestorTable({ days }: { days: InvestorDay[] }) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <h3 className="text-xs font-medium text-neutral-400">
          투자자별 순매수 <span className="font-normal text-neutral-600">주</span>
        </h3>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-neutral-600">
            <th className="pb-1 text-left font-normal">날짜</th>
            <th className="pb-1 text-right font-normal">개인</th>
            <th className="pb-1 text-right font-normal">외국인</th>
            <th className="pb-1 text-right font-normal">기관</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-800/60">
          {days.map((day) => (
            <tr key={day.date}>
              <td className="py-1 text-neutral-500">{formatShortDate(day.date)}</td>
              <NetCell value={day.individual} />
              <NetCell value={day.foreigner} />
              <NetCell value={day.institution} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function NetCell({ value }: { value: number | null }) {
  if (value === null) {
    return <td className="py-1 text-right text-neutral-600">—</td>
  }
  // 순매수는 방향이 핵심이라 부호를 항상 붙이고, 국내 관례대로 매수(+) 빨강 / 매도(-) 파랑.
  const text = `${value > 0 ? '+' : ''}${value.toLocaleString('ko-KR')}`
  return <td className={`tabular py-1 text-right ${changeColor(value)}`}>{text}</td>
}
