import { useState } from 'react'
import type { ReactNode } from 'react'
import type { AnalysisSegment } from '../../lib/api'

/* 기업 해독 카드 — 서술 분석 결과를 **읽히는 한 장**으로 그린다.
 *
 * 국내(사업보고서)와 미국(10-K)이 이 파일 하나를 함께 쓴다. 두 화면이 각자 문단을
 * 그리고 있었고 벌써 조금씩 갈라지기 시작했다 — 카드 컴포넌트를 뽑았던 것과 같은 이유로
 * 여기서 합친다.
 *
 * ── 왜 이렇게 바꿨나 ──────────────────────────────────────────────────
 * 지금까지 분석 결과는 **문단과 점 목록**이었다. 정보는 다 있는데 읽히지가 않았다.
 * 사용자가 '타민더마켓'의 디즈니 기업 해독 카드를 보여 주며 저렇게 만들어 달라고 했다.
 * 그 카드에서 가져온 것은 다음 셋이다.
 *
 *   1. **한 문장이 맨 위에 크게 온다.** 나머지를 안 읽어도 이건 남는다.
 *      원본은 이걸 '2분 드릴'이라 부른다 — 2분 안에 설명 못 하면 모르는 것이다.
 *   2. **번호가 붙은 구획.** 열 개 항목이 늘 같은 순서로 온다는 약속이 카드를 카드로
 *      만든다. 오늘은 사업, 내일은 위험이 먼저 나오면 그건 그냥 글이다.
 *   3. **끝에 "아직 모르는 것"을 남긴다.** 답을 아는 척하지 않는 자리.
 *
 * ── 가져오지 않은 것 ──────────────────────────────────────────────────
 * 원본 카드에는 부문별 매출·영업이익 표와 막대그래프가 있다. **우리는 아직 그 숫자가
 * 없다.** 부문별 실적은 XBRL 의 segment 태그를 따로 파야 나오고, 우리 DB 에는 전사
 * 합계만 있다. 없는 숫자를 LLM 에게 물어 채우는 것은 절대 규칙 3 이 금지한다.
 * 그래서 부문은 **이름과 설명만** 카드로 그린다. 숫자는 옆의 `재무` 탭이 맡는다.
 *
 * ── 색을 쓰지 않는 이유 ───────────────────────────────────────────────
 * 원본은 히어로 패널을 파랗게 칠한다. 이 화면에서는 안 된다 — 파랑은 하락, 빨강은
 * 상승이라는 뜻을 이미 갖고 있다(포커스 링을 무채색으로 둔 것과 같은 이유).
 * 그래서 강조를 색이 아니라 **크기·굵기·표면**으로 만든다. 시세 숫자 옆에서 색이
 * 방향으로 오독되는 것보다 이쪽이 낫다.
 */

export type DecoderRisk = {
  title: string
  why_it_matters: string
}

type Props = {
  oneLiner: string | null
  businessSummary: string | null
  segments: AnalysisSegment[]
  /** 이 회사에 특유한 위험. 앞의 셋을 크게 보여주고 나머지는 접는다. */
  realRisks: DecoderRisk[]
  /** 모든 보고서에 붙는 정형 문구. 제목만 한 줄로. */
  boilerplateRisks: string[]
  mdnaPoints: string[]
  moat: string | null
  openQuestions: string[]
  /** 위험 항목에 붙는 꼬리표. 미국은 "실질", 국내는 출처 이름이 온다. */
  riskTag?: (risk: DecoderRisk, index: number) => string | null
  /** 카드 맨 아래 각주(회계연도·제출일·원문 링크). */
  footer: ReactNode
  /** 이 분석이 무엇이고 무엇이 아닌지. 맨 위 안내. */
  scopeNote: ReactNode
}

// 크게 보여줄 위험의 수. 원본 카드는 "나열이 아니라 이야기로, 딱 3개"라고 못 박는다.
// 여섯 개를 같은 크기로 늘어놓으면 무엇이 중한지가 사라진다.
const FEATURED_RISKS = 3

export function DecoderCard({
  oneLiner,
  businessSummary,
  segments,
  realRisks,
  boilerplateRisks,
  mdnaPoints,
  moat,
  openQuestions,
  riskTag,
  footer,
  scopeNote,
}: Props) {
  const featured = realRisks.slice(0, FEATURED_RISKS)
  const rest = realRisks.slice(FEATURED_RISKS)

  // 번호는 실제로 그려진 구획에만 붙는다. 부문이 없는 회사에서 ②가 비면
  // 카드가 고장난 것처럼 보인다.
  let step = 0
  const next = () => (step += 1)

  return (
    <div className="space-y-5 text-sm">
      {scopeNote}

      {oneLiner && <Hero text={oneLiner} />}

      {businessSummary && (
        <Section n={next()} title="이 회사가 하는 일">
          <p className="leading-relaxed text-neutral-300">{businessSummary}</p>
        </Section>
      )}

      {segments.length > 0 && (
        <Section n={next()} title="사업 부문" note="무엇을 파는가">
          {/* 점 목록 대신 격자. 부문이 몇 개이고 각각 무엇인지가 한눈에 들어온다. */}
          <div className="grid gap-1.5 sm:grid-cols-2">
            {segments.map((segment) => (
              <div
                key={segment.name}
                className="rounded border border-neutral-800 bg-neutral-950/60 px-2.5 py-2"
              >
                <div className="text-xs font-medium text-neutral-200">{segment.name}</div>
                {segment.what && (
                  <div className="mt-0.5 text-[11px] leading-relaxed text-neutral-500">
                    {segment.what}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {featured.length > 0 && (
        <Section n={next()} title="이 회사에 특유한 위험" note={`중요한 순 ${featured.length}건`}>
          <ol className="space-y-3">
            {featured.map((risk, i) => (
              <li key={risk.title} className="flex gap-2.5">
                {/* 번호를 매기면 "몇 개짜리 목록"인지가 먼저 읽힌다. */}
                <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-neutral-800 text-[11px] font-medium text-neutral-300">
                  {i + 1}
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <span className="font-medium text-neutral-200">{risk.title}</span>
                    {riskTag?.(risk, i) && (
                      <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-400/90">
                        {riskTag(risk, i)}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-neutral-400">
                    {risk.why_it_matters}
                  </p>
                </div>
              </li>
            ))}
          </ol>

          {rest.length > 0 && <MoreRisks risks={rest} start={FEATURED_RISKS} />}
        </Section>
      )}

      {mdnaPoints.length > 0 && (
        <Section n={next()} title="경영진이 든 이유" note="실적 변화의 원인으로 회사가 말한 것">
          <ul className="space-y-1.5">
            {mdnaPoints.map((point) => (
              <li key={point} className="flex gap-2 text-xs leading-relaxed text-neutral-400">
                <span className="mt-1.5 size-1 shrink-0 rounded-full bg-neutral-600" />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {moat && (
        <Section n={next()} title="경쟁 구도">
          <p className="text-xs leading-relaxed text-neutral-400">{moat}</p>
        </Section>
      )}

      {boilerplateRisks.length > 0 && (
        <Section
          n={next()}
          title="형식적 위험"
          note="모든 보고서에 붙는 정형 문구 — 걸러낸 것"
        >
          <div className="flex flex-wrap gap-1">
            {boilerplateRisks.map((title) => (
              <span
                key={title}
                className="rounded border border-neutral-800 px-1.5 py-0.5 text-[11px] text-neutral-500"
              >
                {title}
              </span>
            ))}
          </div>
        </Section>
      )}

      {openQuestions.length > 0 && (
        <Section n={next()} title="아직 모르는 것" note="이 보고서로는 답이 안 나온 것">
          {/* 카드의 마지막 자리. 답을 아는 척하지 않고 다음에 볼 것을 남긴다. */}
          <ul className="space-y-1.5">
            {openQuestions.map((question) => (
              <li key={question} className="flex gap-2 text-xs leading-relaxed text-neutral-400">
                <span className="shrink-0 text-neutral-600">?</span>
                <span>{question}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {footer}
    </div>
  )
}

/** ① 2분 드릴. 나머지를 안 읽어도 이것만은 남는 한 문장. */
function Hero({ text }: { text: string }) {
  return (
    <div className="rounded-lg border-l-2 border-neutral-500 bg-surface-raised px-3.5 py-3">
      <div className="text-[11px] tracking-wide text-neutral-500">
        2분 드릴 — 이 회사는 뭘로 돈을 버나
      </div>
      <p className="mt-1.5 text-base font-medium leading-relaxed text-neutral-100">{text}</p>
    </div>
  )
}

/** 네 번째부터의 위험. 접어 두되 몇 건인지는 밝힌다. */
function MoreRisks({ risks, start }: { risks: DecoderRisk[]; start: number }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="mt-2.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="rounded px-1 py-0.5 text-[11px] text-neutral-500 transition-colors hover:text-neutral-300"
      >
        {open ? '접기' : `나머지 ${risks.length}건 더 보기`}
      </button>
      {open && (
        <ol className="mt-2 space-y-2.5">
          {risks.map((risk, i) => (
            <li key={risk.title} className="flex gap-2.5">
              <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-neutral-800/60 text-[11px] text-neutral-500">
                {start + i + 1}
              </span>
              <div className="min-w-0">
                <div className="text-xs font-medium text-neutral-300">{risk.title}</div>
                <p className="mt-0.5 text-xs leading-relaxed text-neutral-500">
                  {risk.why_it_matters}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

/** 번호 붙은 구획. 번호가 카드에 순서라는 약속을 준다. */
function Section({
  n,
  title,
  note,
  children,
}: {
  n: number
  title: string
  note?: string
  children: ReactNode
}) {
  return (
    <section>
      <h3 className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="flex size-[18px] shrink-0 items-center justify-center rounded-full bg-neutral-700 text-[10px] font-medium text-neutral-200">
          {n}
        </span>
        <span className="text-xs font-medium text-neutral-300">{title}</span>
        {note && <span className="text-[11px] text-neutral-600">{note}</span>}
      </h3>
      {children}
    </section>
  )
}
