import { useEffect, useState } from 'react'
import { fetchUsValuation, type UsValuation } from '../lib/api'

// 미국 밸류에이션. 국내(`ValuationBox`)와 계산은 같고 **밝혀야 할 것이 다르다.**
//
// 국내는 "상장주식수가 보통주만"이라는 것을 밝혔다. 미국은 그 자리에 **주식수 기준일**이
// 온다. SEC 가 주는 발행주식수는 회계연도별 값이 아니라 가장 최근 제출 서류 표지의
// 수량이라, 2025 회계연도 재무에 2026년 7월 주식수가 붙는다. 시가총액은 그것이 맞지만
// (지금 주식수 × 지금 주가) 두 시점이 다르다는 것은 알고 봐야 한다.
//
// 지배주주 구분은 따로 하지 않는다. us-gaap 이 `NetIncomeLoss`(모회사 몫)와
// `ProfitLoss`(비지배지분 포함)를 다른 계정으로 두고, 우리 추출기가 앞의 것을 먼저 본다.

type Props = {
  ticker: string
}

export function UsValuationBox({ ticker }: Props) {
  const [data, setData] = useState<UsValuation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setData(null)

    fetchUsValuation(ticker)
      .then((result) => {
        if (!cancelled) setData(result)
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
  }, [ticker])

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div className="border-b border-neutral-800 px-3 py-2 text-xs text-neutral-400">
        밸류에이션
        <span className="ml-1 text-neutral-600">PER · PBR · 배당수익률</span>
      </div>
      <div className="px-3 py-2">
        {loading && !data ? (
          <p className="text-xs text-neutral-500">지표를 계산하는 중…</p>
        ) : error || !data ? (
          <p className="text-xs text-neutral-500">{error ?? '지표를 낼 수 없습니다.'}</p>
        ) : (
          <>
            <dl className="grid grid-cols-3 gap-x-3 gap-y-1">
              <Metric
                label="PER"
                value={data.per}
                suffix="배"
                note={data.per_note}
                sub={data.eps !== null ? `EPS $${data.eps}` : undefined}
              />
              <Metric
                label="PBR"
                value={data.pbr}
                suffix="배"
                note={data.pbr_note}
                sub={data.bps !== null ? `BPS $${data.bps}` : undefined}
              />
              <Metric
                label="배당수익률"
                value={data.dividend_yield}
                suffix="%"
                note={data.dividend_note}
                sub={data.dps !== null ? `주당 $${data.dps}` : undefined}
              />
            </dl>

            <div className="mt-2 border-t border-neutral-800 pt-2 text-[11px] leading-relaxed text-neutral-600">
              시가총액 ${(Number(data.market_cap) / 1e9).toLocaleString(undefined, {
                maximumFractionDigits: 1,
              })}
              B = <span className="tabular">${data.price}</span> ×{' '}
              <span className="tabular">
                {(data.shares_outstanding / 1e9).toFixed(2)}B주
              </span>
              <br />
              {data.fiscal_year !== null && (
                <>
                  FY{data.fiscal_year} 10-K ({data.period_end}) 기준
                  <br />
                </>
              )}
              {/* 두 시점이 다르다는 것을 여기서 못 박는다. */}
              발행주식수는 {data.shares_as_of ?? '—'} 기준입니다 — 재무 기간과 다릅니다.
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function Metric({
  label,
  value,
  suffix,
  sub,
  note,
}: {
  label: string
  value: string | null
  suffix: string
  sub?: string
  note: string | null
}) {
  return (
    <div>
      <dt className="text-xs text-neutral-500">{label}</dt>
      {value !== null ? (
        <>
          <dd className="tabular text-sm text-neutral-100">
            {value}
            <span className="ml-0.5 text-xs text-neutral-500">{suffix}</span>
          </dd>
          {sub && <dd className="tabular text-[11px] text-neutral-600">{sub}</dd>}
        </>
      ) : (
        // 적자라서 없는 것과 자료를 못 받은 것은 다르다. 이유를 그대로 적는다.
        <dd className="text-[11px] leading-tight text-neutral-500">{note ?? '—'}</dd>
      )}
    </div>
  )
}
