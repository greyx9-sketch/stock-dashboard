import { useEffect, useState } from 'react'
import { fetchPeers, type ScreenResult } from '../lib/api'
import { MetricTable } from './MetricTable'
import { Card } from './ui/Card'
import { Skeleton } from './ui/Skeleton'

// 동종업계 비교. 기획서 5.4 — "같은 업종 종목의 밸류에이션·성장률 나열".
//
// **업종은 DART 기업개황의 표준산업분류로 묶는다.** 그 분류에 두 가지 한계가 있고,
// 둘 다 화면에 밝힌다:
//
//   1. 업종'명'이 없다. 코드→이름 대응표를 우리가 갖고 있지 않아서, 코드를 그대로 적고
//      회사 이름들로 읽게 한다. 지어낸 업종명을 붙이지 않는다.
//   2. 지주회사는 **사업 내용이 아니라 법적 형태**로 묶인다. KB금융과 HD한국조선해양이
//      같은 분류에 들어간다. 감추지 않고 그렇다고 적는다 — 설명이 있으면 사람이 걸러
//      읽을 수 있고, 비워 두는 것보다 낫다.

type Props = {
  symbol: string
}

export function PeerComparison({ symbol }: Props) {
  const [data, setData] = useState<ScreenResult | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setData(null)

    fetchPeers(symbol, 10)
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch(() => {
        // 비교는 곁다리다. 실패해도 상세 화면의 나머지는 그대로 보여야 한다.
        if (!cancelled) setData(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [symbol])

  if (loading) {
    return (
      <Shell>
        <Skeleton rows={6} label="동종업계를 찾는 중…" className="px-3 py-3" />
      </Shell>
    )
  }

  // 업종을 모르거나 같은 업종에 아는 종목이 없으면 아예 그리지 않는다.
  // 빈 표를 두면 "동종업계가 없는 회사"로 잘못 읽힌다.
  if (!data || data.rows.length <= 1) return null

  return (
    <Shell code={data.industry_code}>
      <MetricTable rows={data.rows} highlight={symbol} />
      <div className="border-t border-neutral-800 px-3 py-2 text-[11px] leading-relaxed text-neutral-600">
        표준산업분류 {data.industry_code} 로 묶었습니다. 주가는 {data.trade_date} 확정 종가
        기준입니다.
        {data.holding_company && (
          <>
            <br />
            <span className="text-neutral-500">
              이 종목은 지주회사로 분류돼 있습니다.
            </span>{' '}
            표준산업분류는 사업 내용이 아니라 법적 형태로 묶으므로, 하는 일이 전혀 다른
            지주회사들이 함께 나옵니다.
          </>
        )}
      </div>
    </Shell>
  )
}

function Shell({ code, children }: { code?: string | null; children: React.ReactNode }) {
  return (
    <Card
      title="동종업계 비교"
      hint={code ? `표준산업분류 ${code}` : '같은 업종 종목의 지표'}
      bodyClassName=""
    >
      {children}
    </Card>
  )
}
