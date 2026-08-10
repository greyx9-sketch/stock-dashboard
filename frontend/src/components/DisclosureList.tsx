import { useEffect, useState } from 'react'
import { fetchDisclosures } from '../lib/api'
import type { DisclosureItem } from '../lib/api'

// 공시 목록.
//
// 유형 필터가 핵심이다. 필터 없이 보면 대기업일수록 임원 소유상황보고서로 도배돼서
// 정작 봐야 할 사업보고서·주요사항보고가 묻힌다(삼성전자는 최근 1년 반 공시 3,400건 중
// 3,328건이 지분공시였다). 그래서 기본값을 "정기공시"로 둔다.

const FILTERS: { key: string | null; label: string }[] = [
  { key: 'A', label: '정기' },
  { key: 'B', label: '주요사항' },
  { key: 'I', label: '거래소' },
  { key: 'D', label: '지분' },
  { key: null, label: '전체' },
]

const PERIOD_DAYS = 730
const COUNT = 20

type Props = {
  symbol: string
}

export function DisclosureList({ symbol }: Props) {
  const [reportType, setReportType] = useState<string | null>('A')
  const [items, setItems] = useState<DisclosureItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchDisclosures(symbol, { days: PERIOD_DAYS, count: COUNT, reportType })
      .then((result) => {
        if (!cancelled) setItems(result.disclosures)
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message)
          setItems([])
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [symbol, reportType])

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div className="flex flex-wrap items-center gap-1 border-b border-neutral-800 px-3 py-2">
        <span className="mr-1 text-xs text-neutral-400">공시</span>
        {FILTERS.map((filter) => (
          <button
            key={filter.label}
            onClick={() => setReportType(filter.key)}
            className={`rounded px-2 py-0.5 text-xs transition-colors ${
              reportType === filter.key
                ? 'bg-neutral-100 text-neutral-900'
                : 'text-neutral-400 hover:bg-neutral-800'
            }`}
          >
            {filter.label}
          </button>
        ))}
        {loading && <span className="ml-auto text-xs text-neutral-600">불러오는 중…</span>}
      </div>

      {error ? (
        <p className="px-3 py-4 text-xs text-red-300">{error}</p>
      ) : items.length === 0 && !loading ? (
        <p className="px-3 py-4 text-xs text-neutral-500">최근 2년간 해당 공시가 없습니다.</p>
      ) : (
        <ul className="max-h-72 divide-y divide-neutral-800/70 overflow-y-auto">
          {items.map((item) => (
            <li key={item.receipt_no}>
              {/* DART 원문으로 나가는 링크다. 외부 사이트이므로 새 탭에서 연다. */}
              <a
                href={item.viewer_url}
                target="_blank"
                rel="noreferrer"
                className="flex gap-3 px-3 py-2 text-sm transition-colors hover:bg-neutral-800/60"
              >
                <span className="tabular shrink-0 text-xs text-neutral-500">
                  {item.received_date.slice(2).replace(/-/g, '.')}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-neutral-200">{item.report_name}</span>
                  {(item.filer_name || item.remark) && (
                    <span className="block truncate text-xs text-neutral-500">
                      {item.filer_name}
                      {item.remark && ` · ${item.remark}`}
                    </span>
                  )}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
