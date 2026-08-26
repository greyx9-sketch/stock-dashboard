import { useEffect, useState } from 'react'
import { fetchValuation, type Valuation } from '../lib/api'
import { formatBigWon } from '../lib/format'
import { Card } from './ui/Card'
import { Metric } from './ui/Metric'
import { Empty, ErrorBox, Loading } from './ui/Status'

// 밸류에이션 — PER · PBR · 배당수익률. 기획서 5.2.
//
// 이 화면의 어려운 부분은 계산이 아니라 **무엇으로 낸 값인지 밝히는 것**이다. 같은
// "PER" 이라도 분모를 무엇으로 잡았느냐에 따라 숫자가 달라진다. 그래서 세 줄짜리
// 지표 아래에 근거를 그대로 적는다:
//
//   - 어느 회계연도 재무인지 (FY2025 연결)
//   - 지배주주 몫으로 냈는지
//   - 주가가 실시간인지 확정 종가인지 (둘은 기준일이 다르다)
//   - 상장주식수가 보통주만이라는 것
//
// 못 낸 값은 "—" 로 두지 않고 **왜 못 냈는지**를 적는다. 적자라서 PER 이 없는 것과
// 자료를 아직 못 받은 것은 완전히 다른 상황인데, 둘 다 "—" 면 구분이 안 된다.

type Props = {
  symbol: string
}

export function ValuationBox({ symbol }: Props) {
  const [data, setData] = useState<Valuation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setData(null)

    fetchValuation(symbol)
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
  }, [symbol])

  if (loading && !data) {
    return (
      <Shell>
        <Loading label="지표를 계산하는 중…" />
      </Shell>
    )
  }

  if (error) {
    return (
      <Shell>
        <ErrorBox>{error}</ErrorBox>
      </Shell>
    )
  }

  if (!data) {
    return (
      <Shell>
        <Empty title="지표를 낼 수 없습니다." />
      </Shell>
    )
  }

  return (
    <Shell>
      <dl className="grid grid-cols-3 gap-x-3 gap-y-1">
        <Metric
          label="PER"
          value={data.per}
          suffix="배"
          note={data.per_note}
          sub={data.eps !== null ? `EPS ${data.eps.toLocaleString()}원` : undefined}
        />
        <Metric
          label="PBR"
          value={data.pbr}
          suffix="배"
          note={data.pbr_note}
          sub={data.bps !== null ? `BPS ${data.bps.toLocaleString()}원` : undefined}
        />
        <Metric
          label="배당수익률"
          value={data.dividend_yield}
          suffix="%"
          note={data.dividend_note}
          sub={
            data.dps !== null
              ? `주당 ${data.dps.toLocaleString()}원 (${data.dps_year})`
              : undefined
          }
        />
      </dl>

      <div className="mt-2 border-t border-neutral-800 pt-2 text-xs leading-relaxed text-neutral-600">
        시가총액 {formatBigWon(data.market_cap)}원 ={' '}
        <span className="tabular">{data.price.toLocaleString()}원</span>
        <span className="text-neutral-500"> ({data.price_label})</span> ×{' '}
        <span className="tabular">{(data.listed_shares / 100_000_000).toFixed(2)}억주</span>
        <br />
        {data.fiscal_year !== null && (
          <>
            {data.fiscal_year} 사업보고서 · {data.fs_label}
            {/* 별도재무제표에는 비지배지분이 없어 '지배주주 몫'이라는 구분 자체가 없다. */}
            {data.owners_basis
              ? ' · 지배주주 몫 기준 (비지배지분 제외)'
              : ' · 비지배지분 구분 없음'}
            <br />
          </>
        )}
        상장주식수는 보통주만입니다 — 우선주와 자기주식은 빠져 있습니다.
      </div>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <Card title="밸류에이션" hint="PER · PBR · 배당수익률">
      {children}
    </Card>
  )
}
