import { useEffect, useState } from 'react'
import { fetchUsPeers, type UsPeers } from '../lib/api'

// 미국 동종업계 비교. 기획서 6.6.
//
// 국내(`PeerComparison`)와 같은 자리·같은 뜻이지만 **표를 따로 쓴다.** 미국 행에는
// 배당 열이 없고 시가총액이 달러이며, 주가를 못 받으면 지표가 비어 있을 수 있다.
// 국내 표에 억지로 끼워 맞추면 두 화면 모두 읽기 나빠진다.
//
// 국내보다 나은 점이 하나 있다 — **SEC 가 업종 이름을 함께 준다.** DART 는 코드만 주어
// "표준산업분류 26" 이라고만 적을 수 있었는데, 여기서는
// "Semiconductors & Related Devices" 라고 그대로 적는다.
//
// 국내보다 못한 점도 하나 있다 — **아는 종목이 훨씬 적다.** 회사 하나의 재무를 받는 데
// 3~4MB 가 필요해서 토스 거래대금 상위 100종목만 담아 둔다. 그 사실을 아래에 밝힌다.

type Props = {
  ticker: string
}

export function UsPeerComparison({ ticker }: Props) {
  const [data, setData] = useState<UsPeers | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setData(null)

    fetchUsPeers(ticker, 10)
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
  }, [ticker])

  if (loading) {
    return (
      <Shell>
        <p className="px-3 py-3 text-xs text-neutral-500">동종업계를 찾는 중…</p>
      </Shell>
    )
  }

  // 업종을 모르거나 같은 업종에 아는 종목이 없으면 아예 그리지 않는다.
  // 빈 표를 두면 "동종업계가 없는 회사"로 잘못 읽힌다.
  if (!data || data.rows.length <= 1) return null

  return (
    <Shell name={data.sic_description} code={data.sic}>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-neutral-800 text-neutral-500">
              <th className="px-2 py-1.5 text-left font-normal">종목</th>
              <th className="px-2 py-1.5 text-right font-normal">PER</th>
              <th className="px-2 py-1.5 text-right font-normal">PBR</th>
              <th className="px-2 py-1.5 text-right font-normal">ROE</th>
              <th className="px-2 py-1.5 text-right font-normal">매출증가</th>
              <th className="px-2 py-1.5 text-right font-normal">시총</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr
                key={row.ticker}
                className={`border-b border-neutral-900 ${
                  row.ticker === ticker ? 'bg-neutral-800/60' : ''
                }`}
              >
                <td className="px-2 py-1.5">
                  <span className="tabular text-neutral-200">{row.ticker}</span>
                  {row.ticker === ticker && (
                    <span className="ml-1 rounded bg-neutral-700 px-1 text-[10px] text-neutral-200">
                      이 종목
                    </span>
                  )}
                  <div className="truncate text-[11px] text-neutral-600">{row.name}</div>
                </td>
                <Cell value={row.per} />
                <Cell value={row.pbr} />
                <Cell value={row.roe} suffix="%" />
                <Cell value={row.revenue_growth} suffix="%" />
                <td className="tabular px-2 py-1.5 text-right text-neutral-400">
                  {row.market_cap === null
                    ? '—'
                    : `$${(Number(row.market_cap) / 1e9).toLocaleString(undefined, {
                        maximumFractionDigits: 0,
                      })}B`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="border-t border-neutral-800 px-3 py-2 text-[11px] leading-relaxed text-neutral-600">
        SEC 표준산업분류(SIC {data.sic}) 로 묶었습니다.
        {/* 시장 전체가 아니라는 것을 여기서 못 박는다. */}
        <br />
        지표를 아는 미국 종목은 <strong className="text-neutral-500">
          토스 거래대금 상위 100개
        </strong>{' '}
        뿐입니다 — 같은 업종에 이 목록 밖의 회사가 더 있을 수 있습니다.
      </div>
    </Shell>
  )
}

function Cell({ value, suffix = '' }: { value: string | null; suffix?: string }) {
  return (
    <td className="tabular px-2 py-1.5 text-right text-neutral-200">
      {value === null ? '—' : `${value}${suffix}`}
    </td>
  )
}

function Shell({
  name,
  code,
  children,
}: {
  name?: string | null
  code?: string | null
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div className="border-b border-neutral-800 px-3 py-2 text-xs text-neutral-400">
        동종업계 비교
        <span className="ml-1 text-neutral-600">
          {name ?? (code ? `SIC ${code}` : '같은 업종 종목의 지표')}
        </span>
      </div>
      {children}
    </div>
  )
}
