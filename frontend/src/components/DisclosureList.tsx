import { useEffect, useState } from 'react'
import { fetchDisclosures } from '../lib/api'
import type { DisclosureItem } from '../lib/api'
import { Card } from './ui/Card'
import { Skeleton } from './ui/Skeleton'
import { Segmented } from './ui/Segmented'
import { Empty, ErrorBox, Loading } from './ui/Status'

// 공시 목록.
//
// 유형 필터가 핵심이다. 필터 없이 보면 대기업일수록 임원 소유상황보고서로 도배돼서
// 정작 봐야 할 사업보고서·주요사항보고가 묻힌다(삼성전자는 최근 1년 반 공시 3,400건 중
// 3,328건이 지분공시였다). 그래서 기본값을 "정기공시"로 둔다.

// '전체'는 API 에 reportType 을 안 보내는 것이라 값이 null 이다. 다만 화면 상태로는
// 다른 선택지와 같은 자격이어야 해서 'ALL' 이라는 이름을 준 뒤 호출 직전에 null 로 바꾼다.
const FILTERS = [
  { value: 'A', label: '정기' },
  { value: 'B', label: '주요사항' },
  { value: 'I', label: '거래소' },
  { value: 'D', label: '지분' },
  { value: 'ALL', label: '전체' },
] as const

type FilterKey = (typeof FILTERS)[number]['value']

const PERIOD_DAYS = 730
const COUNT = 20

type Props = {
  symbol: string
}

export function DisclosureList({ symbol }: Props) {
  const [reportType, setReportType] = useState<FilterKey>('A')
  const [items, setItems] = useState<DisclosureItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchDisclosures(symbol, {
      days: PERIOD_DAYS,
      count: COUNT,
      reportType: reportType === 'ALL' ? null : reportType,
    })
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
    <Card
      title="공시"
      bodyClassName=""
      meta={loading ? <Loading label="불러오는 중…" /> : undefined}
      actions={
        <Segmented
          label="공시 유형"
          options={FILTERS}
          value={reportType}
          onChange={setReportType}
        />
      }
    >
      {error ? (
        <ErrorBox className="px-3 py-4">{error}</ErrorBox>
      ) : items.length === 0 && loading ? (
        <Skeleton rows={6} label="공시를 받는 중…" className="px-3 py-3" />
      ) : items.length === 0 ? (
        <Empty className="px-3 py-4" title="최근 2년간 해당 공시가 없습니다." />
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
    </Card>
  )
}
