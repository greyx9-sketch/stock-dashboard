import type { ReactNode } from 'react'

/* 위험 지도 — 어떤 성격의 위험이 **언제** 닥치는가.
 *
 * ── 축을 무엇으로 잡았나 ──────────────────────────────────────────────
 * 세로는 **시점**(이미 진행 중 / 다가오는 / 잠재적), 가로는 **성격**(공급망·규제·수요…)이다.
 *
 * 심각도를 축으로 쓰지 않았다. 얼마나 나쁜지는 **판단**이라, 그걸 모델에게 고르게 하면
 * 투자 의견에 가까워진다(프롬프트가 금지하는 것). 시점은 보고서에 사실로 적혀 있다 —
 * 소송이 이미 걸렸는지, 법이 통과됐는데 시행 전인지, 조건이 맞으면 일어난다고만 했는지.
 *
 * ── 왜 격자(matrix)가 아니라 띠(band)인가 ─────────────────────────────
 * 처음엔 시점 × 성격 격자를 그리려 했다. 그런데 위험은 최대 6건이고 성격은 아홉 가지다.
 * 3×9 = 27칸에 6개가 흩어지면 **빈칸이 그림의 대부분**이 되어, 지도가 아니라 고장난 표로
 * 보인다. 좁은 화면에서는 더 심하다.
 *
 * 그래서 시점을 띠로 눕히고 성격은 각 항목의 꼬리표로 붙였다. 알고 싶은 것("당장 걸린
 * 게 뭐고 어떤 종류인가")은 그대로 읽히면서 빈칸이 사라진다.
 *
 * ── 호박색을 여기서는 쓴다 ────────────────────────────────────────────
 * 이 화면에서 호박색은 **주의**를 뜻하고, 단순 분류에 쓰면 안 된다는 것이 카드의 규칙이다.
 * '이미 진행 중'은 분류가 아니라 진짜 주의다 — 소송이 걸려 있거나 이미 실적에 반영된
 * 위험이다. 그래서 첫 띠에만 호박색을 주고 나머지 둘은 무채색으로 둔다.
 * 빨강·파랑은 쓰지 않는다. 이 화면에서 그 둘은 상승·하락이다.
 */

export type MappedRisk = {
  title: string
  category: string
  timing: string
}

/** 위에서 아래로 급한 순. 서버의 `RiskTiming` 과 글자가 같아야 한다. */
const BANDS = [
  {
    timing: '이미 진행 중',
    note: '소송·제재가 걸려 있거나 이미 실적에 나타난 것',
    tone: 'amber' as const,
  },
  { timing: '다가오는', note: '법·계약·만기처럼 시점이 정해진 것', tone: 'plain' as const },
  { timing: '잠재적', note: '조건이 맞으면 일어날 수 있다고만 적힌 것', tone: 'faint' as const },
]

export function RiskMap({ risks }: { risks: MappedRisk[] }) {
  // 비어 있는 띠는 그리지 않는다. "이미 진행 중인 위험 없음"은 좋은 소식이지만,
  // 빈 띠로 보여주면 자료가 안 온 것처럼 읽힌다.
  const bands = BANDS.map((band) => ({
    ...band,
    items: risks.filter((risk) => risk.timing === band.timing),
  })).filter((band) => band.items.length > 0)

  if (bands.length === 0) return null

  return (
    <figure className="m-0">
      <div className="space-y-1.5">
        {bands.map((band) => (
          <Band key={band.timing} label={band.timing} note={band.note} tone={band.tone}>
            {band.items.map((risk) => (
              <li
                key={risk.title}
                className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5 rounded border border-neutral-800 bg-neutral-950/60 px-2 py-1.5"
              >
                <span className="text-xs leading-relaxed text-neutral-300">{risk.title}</span>
                <span className="shrink-0 rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400">
                  {risk.category}
                </span>
              </li>
            ))}
          </Band>
        ))}
      </div>

      <figcaption className="mt-2 text-[11px] leading-relaxed text-neutral-600">
        세로는 <strong className="text-neutral-500">언제</strong>, 꼬리표는{' '}
        <strong className="text-neutral-500">어떤 성격</strong>입니다. 얼마나 나쁜지는 담지
        않습니다 — 그건 판단이고, 이 분석은 보고서에 적힌 것만 옮깁니다.
      </figcaption>
    </figure>
  )
}

function Band({
  label,
  note,
  tone,
  children,
}: {
  label: string
  note: string
  tone: 'amber' | 'plain' | 'faint'
  children: ReactNode
}) {
  const edge =
    tone === 'amber'
      ? 'border-l-amber-500/50'
      : tone === 'plain'
        ? 'border-l-neutral-600'
        : 'border-l-neutral-800'
  const labelColor =
    tone === 'amber'
      ? 'text-amber-400/90'
      : tone === 'plain'
        ? 'text-neutral-300'
        : 'text-neutral-500'

  return (
    <section className={`border-l-2 ${edge} rounded-r bg-neutral-950/30 py-2 pl-2.5 pr-2`}>
      <h4 className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className={`text-[11px] font-medium ${labelColor}`}>{label}</span>
        <span className="text-[10px] text-neutral-600">{note}</span>
      </h4>
      <ul className="grid gap-1.5 sm:grid-cols-2">{children}</ul>
    </section>
  )
}
