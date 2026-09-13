import { useState } from 'react'
import type { ReactNode } from 'react'
import type { AnalysisSegment, MoneyFlow } from '../../lib/api'
import { MindMap } from './MindMap'
import { MoneyFlowDiagram, hasMoneyFlow } from './MoneyFlowDiagram'
import { RiskMap } from './RiskMap'

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
 * ── 넓게 펴면 도식이 붙는다 (2026-09-14) ──────────────────────────────
 * 사용자가 "그래프나 마인드맵으로 바꿔 달라"고 했다. 글을 그림으로 바꾸려니 **상자를
 * 자를 자리가 없었다** — 한 문장 요약은 한 문장이라 화살표로 잇지 못한다. 그래서
 * 프롬프트에 도식용 **구조**를 더 받고(`money_flow`·위험의 `category`·`timing`,
 * 여전히 수치는 없다) 그것으로 마인드맵·돈의 흐름도·위험 지도를 그린다.
 *
 * **좁은 패널(550px)에서는 그리지 않는다**(`wide`). 도식은 가로로 읽는 그림이라
 * 세 칸이 한 줄에 들어가야 뜻이 산다. 550px 에 넣으면 세로로 쌓여 그냥 목록이 되고,
 * 같은 내용을 두 번 읽히게 할 뿐이다. 넓게 편 화면이 보고서, 패널은 요약이다.
 *
 * ── 아직 가져오지 못한 것 ─────────────────────────────────────────────
 * 원본 카드에는 부문별 매출·영업이익 **막대그래프**가 있다. 그 숫자가 우리에게 없다 —
 * 부문별 실적은 사업보고서 원문의 표를 직접 파싱해야 나오고, 우리 DB 에는 전사 합계만
 * 있다. 없는 숫자를 LLM 에게 물어 채우는 것은 절대 규칙 3 이 금지한다. 그래서 부문은
 * 아직 **이름과 설명만** 그린다.
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
  /** 위험 지도의 가로 꼬리표. 옛 판에는 없어서 없을 수 있다. */
  category?: string
  /** 위험 지도의 세로 띠. 심각도가 아니라 시점이다. */
  timing?: string
}

type Props = {
  oneLiner: string | null
  businessSummary: string | null
  /** 돈의 흐름도의 재료. 세 칸이 다 차 있을 때만 그려진다. */
  moneyFlow: MoneyFlow | null
  /** 도식을 그릴 만큼 넓은 화면인가. 좁은 패널에서는 글만 그린다. */
  wide?: boolean
  /** 마인드맵 줄기에 놓을 회사 이름. `wide` 일 때만 쓰인다. */
  companyName?: string | null
  /** 보고서가 이름을 댄 경쟁사. 없으면 빈 목록. */
  competitors: string[]
  /** 실적 추이 그래프. 넓은 화면에서만 그려진다. 재무는 이 카드가 받지 않고
   *  부르는 쪽이 만들어 넘긴다 — 국내와 미국이 출처도 단위도 다르기 때문이다. */
  performance?: ReactNode
  segments: AnalysisSegment[]
  /** 이 회사에 특유한 위험. 앞의 셋을 크게 보여주고 나머지는 접는다. */
  realRisks: DecoderRisk[]
  /** 모든 보고서에 붙는 정형 문구. 제목만 한 줄로. */
  boilerplateRisks: string[]
  mdnaPoints: string[]
  moat: string | null
  openQuestions: string[]
  /** 위험 제목 옆의 짧은 강조 칩. 미국의 "실질"처럼 **뜻이 있는 표시**에만 쓴다.
   *  호박색은 이 화면에서 주의를 뜻하므로 단순 분류에 쓰면 안 된다. */
  riskBadge?: (risk: DecoderRisk, index: number) => string | null
  /** 이 위험이 보고서 어디서 나왔는지. 각주로 아래에 조용히 붙는다.
   *  국내 사업보고서는 위험요인 장이 따로 없고 여러 장에 흩어져 있어서 출처가 중요하다. */
  riskSource?: (risk: DecoderRisk, index: number) => string | null
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
  moneyFlow,
  wide = false,
  companyName,
  competitors,
  performance,
  segments,
  realRisks,
  boilerplateRisks,
  mdnaPoints,
  moat,
  openQuestions,
  riskBadge,
  riskSource,
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

      {/* 먼저 읽는 지도. 아래 구획들이 몇 개이고 무엇인지를 스크롤 전에 보여준다. */}
      {wide && (
        <MindMap
          title={companyName ?? '이 회사'}
          subtitle={oneLiner}
          branches={[
            { label: '사업 부문', note: '무엇을 파는가', leaves: segments.map((s) => s.name) },
            {
              label: '돈을 내는 쪽',
              note: '누가 내는가',
              leaves: moneyFlow?.revenue_sources.map((r) => r.who) ?? [],
            },
            {
              label: '위험',
              note: '이 회사에 특유한 것',
              leaves: realRisks.map((r) => r.title),
            },
            { label: '경쟁사', note: '보고서가 이름을 댄 곳', leaves: competitors },
            /* '아직 모르는 것'은 가지로 넣지 않는다. 질문은 문장이라 잎으로 자르면
               뜻이 사라지고, 이 지도는 **아는 것의 목차**다. 질문은 보고서 끝자리에
               온전한 문장으로 남는다. */
          ]}
        />
      )}

      {businessSummary && (
        <Section n={next()} title="이 회사가 하는 일">
          <p className="leading-relaxed text-neutral-300">{businessSummary}</p>
        </Section>
      )}

      {wide && hasMoneyFlow(moneyFlow) && (
        <Section n={next()} title="돈의 흐름" note="사와서 → 값을 붙여 → 팔아서">
          <MoneyFlowDiagram flow={moneyFlow} companyName={companyName} />
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

      {/* 사업을 본 다음 실적, 그다음 위험. 보고서를 읽는 순서다 —
          무엇을 파는지 모르고 매출 그래프를 보면 아무 뜻도 없다. */}
      {wide && performance && (
        <Section n={next()} title="실적이 어땠나" note="모양을 보는 그림 — 값은 재무 탭에">
          {performance}
        </Section>
      )}

      {wide && realRisks.some((risk) => risk.timing) && (
        <Section n={next()} title="위험 지도" note="어떤 성격의 위험이 언제 닥치는가">
          <RiskMap
            risks={realRisks
              .filter((risk) => risk.timing)
              .map((risk) => ({
                title: risk.title,
                category: risk.category || '기타',
                timing: risk.timing as string,
              }))}
          />
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
                    {riskBadge?.(risk, i) && (
                      <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-400/90">
                        {riskBadge(risk, i)}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-neutral-400">
                    {risk.why_it_matters}
                  </p>
                  {riskSource?.(risk, i) && (
                    <p className="mt-1 text-[11px] text-neutral-600">
                      출처: {riskSource(risk, i)}
                    </p>
                  )}
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

      {(moat || competitors.length > 0) && (
        <Section n={next()} title="경쟁 구도">
          {moat && <p className="text-xs leading-relaxed text-neutral-400">{moat}</p>}
          {competitors.length > 0 && (
            <div className="mt-2">
              {/* 보고서가 **이름을 댄** 곳만이다. 업계 상식으로 보태면 어디까지가 공시
                  내용인지가 흐려진다 — 이 카드의 값어치는 그 경계에 있다. */}
              <div className="mb-1 text-[10px] text-neutral-600">보고서가 이름을 댄 경쟁사</div>
              <div className="flex flex-wrap gap-1">
                {competitors.map((name) => (
                  <span
                    key={name}
                    className="rounded border border-neutral-800 bg-neutral-950/60 px-1.5 py-0.5 text-[11px] text-neutral-400"
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>
          )}
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
