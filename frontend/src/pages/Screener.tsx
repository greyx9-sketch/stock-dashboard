import { useCallback, useEffect, useState } from 'react'
import { fetchScreen, type ScreenFilters, type ScreenResult } from '../lib/api'
import { MetricTable } from '../components/MetricTable'
import { StockDetailPanel } from '../components/StockDetailPanel'
import type { Section } from '../lib/useRoute'
import { useLivePrices } from '../lib/useLivePrices'
import { Card } from '../components/ui/Card'
import { Segmented } from '../components/ui/Segmented'
import { Announce, Empty, ErrorBox, Loading } from '../components/ui/Status'

// 스크리너. 기획서 5.4 — "PER 15배 이하 + ROE 10% 이상 같은 조건 필터".
//
// **아는 종목이 몇 개인지 반드시 밝힌다.** 이 화면은 시장 전체를 훑지 않는다. 조건에
// 맞는 종목을 찾으려면 후보 전부의 PER 을 미리 알아야 하는데, 그건 매일 밤 시가총액
// 상위 300종목만 받아 둔다. "조건에 맞는 종목 3개"로만 읽히면 시장에 세 개뿐이라고
// 오해하게 된다.
//
// 조건은 **비워 두면 안 건다.** 처음 열면 유니버스 전체가 시가총액 순으로 나온다 —
// 빈 화면에서 시작하면 무엇을 넣어야 할지 알 수 없다.

const PRESETS = [
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
] as const satisfies readonly { label: string; hint: string; filters: ScreenFilters }[]

const PRESET_OPTIONS = PRESETS.map((preset) => ({
  value: preset.label,
  label: preset.label,
  title: preset.hint,
}))

type NumberFilter = 'per_max' | 'pbr_max' | 'roe_min' | 'yield_min' | 'growth_min'

const NUMBER_KEYS: NumberFilter[] = ['per_max', 'pbr_max', 'roe_min', 'yield_min', 'growth_min']

const FIELDS: { key: NumberFilter; label: string; placeholder: string }[] = [
  { key: 'per_max', label: 'PER 이하', placeholder: '15' },
  { key: 'pbr_max', label: 'PBR 이하', placeholder: '1' },
  { key: 'roe_min', label: 'ROE 이상 %', placeholder: '10' },
  { key: 'yield_min', label: '배당 이상 %', placeholder: '3' },
  { key: 'growth_min', label: '매출증가 이상 %', placeholder: '10' },
]

/**
 * 지금 조건이 어느 프리셋과 똑같은가. 없으면 빈 문자열.
 *
 * 프리셋 버튼 네 개가 **무엇이 눌려 있는지 표시가 없었다.** 눌러도 버튼 모양이 그대로라
 * 방금 누른 것이 먹었는지 알 수 없었고, 숫자를 손으로 고친 뒤에도 프리셋이 여전히
 * 걸려 있는 것처럼 보였다. 조건을 견주어 눌림을 계산한다 — 숫자를 하나라도 고치면
 * 어느 프리셋과도 다르므로 저절로 풀린다.
 */
function activePreset(filters: ScreenFilters): string {
  for (const preset of PRESETS) {
    const wanted = preset.filters as ScreenFilters
    const sameNumbers = NUMBER_KEYS.every(
      (key) => (filters[key] ?? null) === (wanted[key] ?? null),
    )
    if (sameNumbers && filters.sort === wanted.sort && filters.desc === wanted.desc) {
      return preset.label
    }
  }
  return ''
}

type Props = {
  /** 지금 열려 있는 종목. 국내·미국 탭과 같이 주소가 들고 있다(`lib/useRoute`). */
  symbol: string | null
  section: Section
  onSelect: (symbol: string | null) => void
  onSection: (section: Section) => void
}

export function Screener({ symbol, section, onSelect, onSection }: Props) {
  const [filters, setFilters] = useState<ScreenFilters>({ sort: 'market_cap', desc: true })
  const [result, setResult] = useState<ScreenResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // 고른 종목 하나만 현재가를 받는다. 상세 화면은 토스를 따로 부르지 않고 이 값을
  // 쓰도록 만들어져 있다 — 목록 100줄 전부를 폴링하면 구독 한도만 태운다.
  const live = useLivePrices(symbol ? [symbol] : [], 'KR')

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

  const applyPreset = (label: string) => {
    const preset = PRESETS.find((p) => p.label === label)
    if (preset) setFilters({ ...preset.filters, market: filters.market ?? null })
  }

  const clear = () => setFilters({ sort: 'market_cap', desc: true, market: filters.market ?? null })

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_26rem]">
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-sm font-semibold">종목 고르기</span>
          <Segmented
            label="조건 프리셋"
            options={PRESET_OPTIONS}
            value={activePreset(filters)}
            onChange={applyPreset}
          />
          <button
            onClick={clear}
            className="rounded px-2 py-0.5 text-xs text-neutral-500 transition-colors hover:text-neutral-300"
          >
            조건 지우기
          </button>
        </div>

        {/* 라벨이 11px 이었다. 0단계에서 "읽어야 하는 문장은 13px 이상, 11px 은 분류 배지에만"
            이라고 정해 놓고 이 화면만 예외로 남아 있었다. */}
        <Card className="mb-3" bodyClassName="flex flex-wrap items-end gap-2 px-3 py-2">
          {FIELDS.map((field) => (
            <label key={field.key} className="flex flex-col gap-0.5">
              <span className="text-xs text-neutral-500">{field.label}</span>
              <input
                type="number"
                value={filters[field.key] ?? ''}
                onChange={(e) => setNumber(field.key, e.target.value)}
                // 0단계에서 회색을 밝히면서 **빈 칸의 예시 숫자가 입력된 값처럼 보이게** 됐다.
                // 색을 다시 낮추는 대신 "예" 를 붙인다 — 색과 상관없이 예시라는 것이 전달된다.
                placeholder={`예 ${field.placeholder}`}
                className="tabular w-28 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-200 placeholder:text-neutral-600"
              />
            </label>
          ))}
          <label className="flex flex-col gap-0.5">
            <span className="text-xs text-neutral-500">시장</span>
            <select
              value={filters.market ?? ''}
              onChange={(e) => setFilters((prev) => ({ ...prev, market: e.target.value || null }))}
              className="rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-200"
            >
              <option value="">전체</option>
              <option value="KOSPI">KOSPI</option>
              <option value="KOSDAQ">KOSDAQ</option>
            </select>
          </label>
        </Card>

        {error ? (
          <ErrorBox tone="block" onRetry={reload}>
            {error}
          </ErrorBox>
        ) : (
          <>
            {/* **이 화면의 요점이 몇 개가 걸러졌는가**인데, 지금까지는 표 머리글 안에
                작은 회색 글자로 묻혀 있었다. 조건을 바꿔도 바뀐 줄을 몰랐다. */}
            <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
              {result ? (
                <>
                  <span className="text-sm">
                    <span className="tabular text-xl font-semibold text-neutral-100">
                      {result.matched}
                    </span>
                    개 종목이 조건에 맞습니다
                  </span>
                  {/* 시장 전체가 아니라는 것을 여기서 못 박는다. */}
                  <span className="text-xs text-neutral-500">
                    지표를 아는 <span className="tabular">{result.universe}</span>개 중 · 주가는{' '}
                    <span className="tabular">{result.trade_date}</span> 확정 종가
                  </span>
                </>
              ) : (
                <span className="text-sm text-neutral-500">고르는 중…</span>
              )}
              {loading && result && <Loading label="다시 고르는 중…" />}
            </div>

            <Announce>
              {loading || !result ? '' : `조건에 맞는 종목 ${result.matched}개`}
            </Announce>

            <Card flush>
              {result && (
                <MetricTable
                  rows={result.rows}
                  highlight={symbol ?? undefined}
                  onPick={onSelect}
                  sort={filters.sort}
                  desc={filters.desc}
                  onSort={toggleSort}
                />
              )}
            </Card>
          </>
        )}

        <p className="mt-2 text-xs leading-relaxed text-neutral-500">
          지표를 아는 종목은 <strong className="text-neutral-400">시가총액 상위 300개</strong>{' '}
          입니다. 매일 오후 2시에 다시 받습니다. 시장 전체를 훑지 않으므로, 조건에 맞는
          종목이 이 목록 밖에 더 있을 수 있습니다.
          <br />
          PER·PBR·ROE 는 <strong className="text-neutral-400">지배주주 몫</strong> 기준이고,
          적자·자본잠식이면 값을 내지 않아 그 조건에서 빠집니다.
        </p>
      </div>

      {/* 국내·미국 탭과 같은 규칙 — 상세를 화면에 붙잡아 둔다. */}
      <aside className="lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:self-start lg:overflow-y-auto lg:pr-1">
        {symbol ? (
          <StockDetailPanel
            symbol={symbol}
            live={live.bySymbol.get(symbol)}
            market={live.market}
            section={section}
            onSection={onSection}
          />
        ) : (
          <Card bodyClassName="px-3 py-4">
            <Empty
              title="종목을 누르면 여기에 상세가 뜹니다."
              hint="표에서 화살표로 옮기고 Enter 로도 열립니다."
            />
          </Card>
        )}
      </aside>
    </div>
  )
}
