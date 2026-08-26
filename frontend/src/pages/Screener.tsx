import { useCallback, useEffect, useState } from 'react'
import { fetchScreen, type ScreenFilters, type ScreenResult } from '../lib/api'
import { MetricTable } from '../components/MetricTable'
import { StockDetailPanel } from '../components/StockDetailPanel'
import { useLivePrices } from '../lib/useLivePrices'
import { ErrorBox } from '../components/ui/Status'

// 스크리너. 기획서 5.4 — "PER 15배 이하 + ROE 10% 이상 같은 조건 필터".
//
// **아는 종목이 몇 개인지 반드시 밝힌다.** 이 화면은 시장 전체를 훑지 않는다. 조건에
// 맞는 종목을 찾으려면 후보 전부의 PER 을 미리 알아야 하는데, 그건 매일 밤 시가총액
// 상위 300종목만 받아 둔다. "조건에 맞는 종목 3개"로만 읽히면 시장에 세 개뿐이라고
// 오해하게 된다.
//
// 조건은 **비워 두면 안 건다.** 처음 열면 유니버스 전체가 시가총액 순으로 나온다 —
// 빈 화면에서 시작하면 무엇을 넣어야 할지 알 수 없다.

const PRESETS: { label: string; hint: string; filters: ScreenFilters }[] = [
  {
    label: '저PER · 고ROE',
    hint: 'PER 15 이하 + ROE 10% 이상',
    filters: { per_max: 15, roe_min: 10, sort: 'per', desc: false },
  },
  {
    label: '고배당',
    hint: '배당수익률 3% 이상',
    filters: { yield_min: 3, sort: 'dividend_yield', desc: true },
  },
  {
    label: '저PBR',
    hint: 'PBR 1배 이하 + 흑자',
    filters: { pbr_max: 1, roe_min: 0, sort: 'pbr', desc: false },
  },
  {
    label: '성장',
    hint: '매출 증가율 20% 이상',
    filters: { growth_min: 20, sort: 'revenue_growth', desc: true },
  },
]

type NumberFilter = 'per_max' | 'pbr_max' | 'roe_min' | 'yield_min' | 'growth_min'

const FIELDS: { key: NumberFilter; label: string; placeholder: string }[] = [
  { key: 'per_max', label: 'PER 이하', placeholder: '15' },
  { key: 'pbr_max', label: 'PBR 이하', placeholder: '1' },
  { key: 'roe_min', label: 'ROE 이상 %', placeholder: '10' },
  { key: 'yield_min', label: '배당 이상 %', placeholder: '3' },
  { key: 'growth_min', label: '매출증가 이상 %', placeholder: '10' },
]

export function Screener() {
  const [filters, setFilters] = useState<ScreenFilters>({ sort: 'market_cap', desc: true })
  const [result, setResult] = useState<ScreenResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [picked, setPicked] = useState<string | null>(null)

  // 고른 종목 하나만 현재가를 받는다. 상세 화면은 토스를 따로 부르지 않고 이 값을
  // 쓰도록 만들어져 있다 — 목록 100줄 전부를 폴링하면 구독 한도만 태운다.
  const live = useLivePrices(picked ? [picked] : [], 'KR')

  const reload = useCallback(() => {
    setLoading(true)
    fetchScreen({ ...filters, limit: 100 })
      .then((r) => {
        setResult(r)
        setError(null)
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [filters])

  useEffect(reload, [reload])

  const setNumber = (key: NumberFilter, raw: string) => {
    const value = raw.trim() === '' ? null : Number(raw)
    setFilters((prev) => ({ ...prev, [key]: Number.isNaN(value) ? null : value }))
  }

  const toggleSort = (key: string) => {
    setFilters((prev) => ({
      ...prev,
      sort: key,
      // 같은 열을 다시 누르면 방향만 바꾼다. 다른 열이면 그 열에 자연스러운 방향으로.
      desc: prev.sort === key ? !prev.desc : !['per', 'pbr'].includes(key),
    }))
  }

  const clear = () =>
    setFilters({ sort: 'market_cap', desc: true, market: filters.market ?? null })

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_26rem]">
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-sm font-semibold">종목 고르기</span>
          {PRESETS.map((preset) => (
            <button
              key={preset.label}
              title={preset.hint}
              onClick={() => setFilters({ ...preset.filters, market: filters.market ?? null })}
              className="rounded border border-neutral-800 px-2 py-0.5 text-xs text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-neutral-200"
            >
              {preset.label}
            </button>
          ))}
          <button
            onClick={clear}
            className="rounded px-2 py-0.5 text-xs text-neutral-600 hover:text-neutral-300"
          >
            조건 지우기
          </button>
        </div>

        <div className="mb-3 flex flex-wrap items-end gap-2 rounded-lg border border-neutral-800 bg-neutral-900/40 px-3 py-2">
          {FIELDS.map((field) => (
            <label key={field.key} className="flex flex-col gap-0.5">
              <span className="text-[11px] text-neutral-500">{field.label}</span>
              <input
                type="number"
                value={filters[field.key] ?? ''}
                onChange={(e) => setNumber(field.key, e.target.value)}
                placeholder={field.placeholder}
                className="tabular w-24 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs text-neutral-200 placeholder:text-neutral-700"
              />
            </label>
          ))}
          <label className="flex flex-col gap-0.5">
            <span className="text-[11px] text-neutral-500">시장</span>
            <select
              value={filters.market ?? ''}
              onChange={(e) =>
                setFilters((prev) => ({ ...prev, market: e.target.value || null }))
              }
              className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs text-neutral-200"
            >
              <option value="">전체</option>
              <option value="KOSPI">KOSPI</option>
              <option value="KOSDAQ">KOSDAQ</option>
            </select>
          </label>
        </div>

        {error ? (
          <ErrorBox>
            {error}
          </ErrorBox>
        ) : (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
            <div className="border-b border-neutral-800 px-3 py-2 text-xs text-neutral-500">
              {loading && !result ? (
                '고르는 중…'
              ) : result ? (
                <>
                  <span className="text-neutral-300">{result.matched}개</span> 종목이 조건에
                  맞습니다
                  {/* 시장 전체가 아니라는 것을 여기서 못 박는다. */}
                  <span className="text-neutral-600">
                    {' '}
                    · 지표를 아는 {result.universe}개 중 · 주가는 {result.trade_date} 확정 종가
                  </span>
                </>
              ) : null}
            </div>
            {result && (
              <MetricTable
                rows={result.rows}
                highlight={picked ?? undefined}
                onPick={setPicked}
                sort={filters.sort}
                desc={filters.desc}
                onSort={toggleSort}
              />
            )}
          </div>
        )}

        <p className="mt-2 text-[11px] leading-relaxed text-neutral-600">
          지표를 아는 종목은 <strong className="text-neutral-500">시가총액 상위 300개</strong>{' '}
          입니다. 매일 오후 2시에 다시 받습니다. 시장 전체를 훑지 않으므로, 조건에 맞는
          종목이 이 목록 밖에 더 있을 수 있습니다.
          <br />
          PER·PBR·ROE 는 <strong className="text-neutral-500">지배주주 몫</strong> 기준이고,
          적자·자본잠식이면 값을 내지 않아 그 조건에서 빠집니다.
        </p>
      </div>

      <div>
        {picked ? (
          <StockDetailPanel
            symbol={picked}
            live={live.bySymbol.get(picked)}
            market={live.market}
          />
        ) : (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 px-3 py-4 text-xs text-neutral-500">
            종목을 누르면 여기에 상세가 뜹니다.
          </div>
        )}
      </div>
    </div>
  )
}
