// 공시 분석을 **claude.ai 에 붙여넣을 프롬프트**로 뽑는다.
//
// ── 왜 이게 필요한가 ────────────────────────────────────────────────────
// 이 보고서에는 **일부러 하지 않는 것**들이 있다. 투자 의견을 쓰지 않고, 원문에 없는
// 지식으로 보충하지 않고, 최근 뉴스를 모른다. 그건 이 카드가 "공시에 적힌 것"만
// 다루기로 했기 때문이지 쓸모없어서가 아니다.
//
// 그 못 하는 것들이 곧 사람이 claude.ai 에서 이어서 물어볼 거리다. 여기서 하는 일은
// **자료를 다시 타이핑하지 않게 해 주는 것**이다.
//
// ── 돈 이야기 ───────────────────────────────────────────────────────────
// 이 프로젝트에서 분석 한 건은 200~410원이 든다(실측). claude.ai 는 구독이라 붙여넣고
// 묻는 것은 **추가 비용이 0원**이다. `docs/외부저장소조사.md` 에 "API 를 구독 사용량으로
// 돌릴 방법은 없다"고 결론을 적어 두었는데, 사람이 복사해 붙여넣는 이 경로가 그 결론을
// 우회하는 유일한 길이다.
//
// ── 숫자를 같이 싣는다 ──────────────────────────────────────────────────
// 절대 규칙 3은 **LLM 이 수치를 만드는 것**을 막는 규칙이지, 우리가 XBRL 에서 계산한
// 값을 프롬프트에 넣는 것을 막지 않는다. 오히려 넣어야 한다 — 숫자 없이 서술만 주면
// 받는 쪽이 기억으로 숫자를 지어낸다. 그래서 프롬프트 머리에 **무엇이 원자료이고
// 무엇이 해석인지**를 못 박는다.

export type PromptRisk = {
  title: string
  why_it_matters: string
  category?: string
  timing?: string
}

export type PromptFinancialRow = {
  label: string
  revenue: number | null
  operatingIncome: number | null
  operatingMargin: string | null
}

export type PromptFacts = {
  /** 화면에 쓰는 이름 그대로. 예: '삼성전자 (005930)' */
  company: string
  /** 예: '2025 회계연도 사업보고서 (2026-03-10 접수)' */
  period: string
  sourceUrl: string | null
  oneLiner: string | null
  businessSummary: string | null
  moneyFlow: {
    inputs: string[]
    engine: string
    revenue_sources: { who: string; pays_for: string }[]
  } | null
  segments: { name: string; what: string }[]
  competitors: string[]
  risks: PromptRisk[]
  mdnaPoints: string[]
  moat: string | null
  openQuestions: string[]
  financials: PromptFinancialRow[]
  /** 금액을 사람이 읽는 말로. 국내는 조·억, 미국은 T·B. */
  formatAmount: (value: number) => string
}

export type PromptPresetId = 'open_questions' | 'bear_case' | 'whats_changed' | 'peers'

export type PromptPreset = {
  id: PromptPresetId
  label: string
  /** 단추 아래 한 줄. 이걸 고르면 무엇을 시키는지. */
  hint: string
  /** 자료 뒤에 붙는 지시문. */
  ask: string
  /** 이 지시가 성립하려면 자료에 무엇이 있어야 하는가. 없으면 고를 수 없게 한다. */
  requires?: (facts: PromptFacts) => boolean
}

export const PRESETS: PromptPreset[] = [
  {
    id: 'open_questions',
    label: '남은 질문 메우기',
    hint: '보고서가 스스로 "답이 안 나온다"고 남긴 것들',
    requires: (f) => f.openQuestions.length > 0,
    ask: `위 "이 보고서로는 답이 안 나온 것"에 하나씩 답해 주세요.

- 웹에서 찾을 수 있는 것은 찾아서 답하되, **출처와 그 자료의 날짜**를 반드시 밝혀 주세요.
- 찾지 못한 것은 "찾지 못했다"고 쓰고, 어디를 봐야 나올지를 알려 주세요.
- 추측으로 메우지 마세요. 위 재무 수치는 공시 원자료이니 그것과 어긋나는 답은 하지 마세요.`,
  },
  {
    id: 'bear_case',
    label: '반대 논거 세우기',
    hint: '이 보고서가 일부러 하지 않는 것 — 약세 시각',
    ask: `이 회사에 대한 **가장 강한 약세 논거**를 세워 주세요.

- 위 위험 목록에서 시작하되, 목록에 없는 것도 근거가 있으면 보태 주세요.
- 각 논거마다 "무엇이 관찰되면 이 논거가 맞다고 볼 수 있는지"를 함께 적어 주세요.
- 매수·매도 의견이나 목표주가는 쓰지 마세요. **논거와 그 검증 방법**만 주세요.
- 마지막에, 이 약세 논거들이 틀릴 수 있는 지점도 한 문단으로 적어 주세요.`,
  },
  {
    id: 'whats_changed',
    label: '그 뒤 뭐가 바뀌었나',
    hint: '자료는 공시 기준이라 묵어 있습니다',
    ask: `위 자료는 공시 시점 기준이라 지금과 차이가 있을 수 있습니다.

그 이후 이 회사에 무슨 일이 있었는지 웹에서 찾아, 위 내용을 **세 칸으로 갈라** 주세요.

1. **여전히 유효한 것**
2. **바뀐 것** — 무엇이 어떻게 바뀌었는지, 출처와 날짜
3. **새로 생긴 것** — 위 자료에 아예 없던 사건

각 항목에 근거 링크를 붙여 주세요. 확인되지 않은 소문은 그렇다고 표시해 주세요.`,
  },
  {
    id: 'peers',
    label: '경쟁사와 견주기',
    hint: '보고서가 이름을 댄 경쟁사 기준',
    requires: (f) => f.competitors.length > 0,
    ask: `위에 적힌 경쟁사들과 이 회사를 **같은 잣대로** 비교해 주세요.

- 비교 항목을 먼저 정하고(사업 구조 / 돈을 내는 쪽 / 원가 구조 / 규제 노출 등), 그 표를 채워 주세요.
- 숫자를 쓸 때는 출처와 기준 시점을 밝혀 주세요. 위 재무 수치는 공시 원자료입니다.
- 어느 쪽이 낫다는 결론보다, **무엇이 다른지**와 그 차이가 어디서 오는지를 적어 주세요.`,
  },
]

/** 자료가 없으면 빈 문자열. 부르는 쪽이 그것만 걸러낸다. */
function section(title: string, body: string | null): string {
  return body && body.trim() ? `## ${title}\n${body.trim()}` : ''
}

function bullets(items: string[]): string {
  return items.map((item) => `- ${item}`).join('\n')
}

/** 재무를 표로. 파이프 표는 붙여넣었을 때 claude.ai 가 표로 읽는다. */
function financialTable(facts: PromptFacts): string {
  if (facts.financials.length === 0) return ''
  const head = '| 기간 | 매출 | 영업이익 | 영업이익률 |\n| --- | --- | --- | --- |'
  const rows = facts.financials.map((row) => {
    const revenue = row.revenue === null ? '—' : facts.formatAmount(row.revenue)
    const profit =
      row.operatingIncome === null ? '—' : facts.formatAmount(row.operatingIncome)
    const margin = row.operatingMargin ? `${row.operatingMargin}%` : '—'
    return `| ${row.label} | ${revenue} | ${profit} | ${margin} |`
  })
  return `${head}\n${rows.join('\n')}`
}

function moneyFlowText(facts: PromptFacts): string {
  const flow = facts.moneyFlow
  if (!flow || (flow.inputs.length === 0 && flow.revenue_sources.length === 0)) return ''
  const lines: string[] = []
  if (flow.inputs.length > 0) lines.push(`- 사오는 것: ${flow.inputs.join(', ')}`)
  if (flow.engine) lines.push(`- 값을 붙이는 지점: ${flow.engine}`)
  for (const source of flow.revenue_sources) {
    lines.push(`- 돈을 내는 쪽: ${source.who} — ${source.pays_for}`)
  }
  return lines.join('\n')
}

function riskText(risks: PromptRisk[]): string {
  return risks
    .map((risk) => {
      // 시점·성격이 있으면 앞에 붙인다. 옛 판의 분석에는 없을 수 있다.
      const tags = [risk.timing, risk.category].filter(Boolean).join(' · ')
      const head = tags ? `**${risk.title}** (${tags})` : `**${risk.title}**`
      return `- ${head}\n  ${risk.why_it_matters}`
    })
    .join('\n')
}

/**
 * 붙여넣을 프롬프트 한 덩어리.
 *
 * 머리에 **무엇이 원자료이고 무엇이 해석인지**를 먼저 못 박는다. 이걸 빼면 받는 쪽이
 * 우리 서술을 사실로 읽고, 빠진 숫자를 자기 기억으로 메운다 — 이 프로젝트가 절대 규칙
 * 3으로 막아 온 바로 그 일이 화면 밖에서 일어난다.
 */
export function buildPrompt(facts: PromptFacts, preset: PromptPreset): string {
  // 머리말은 **줄 단위**로 짜고, 본문은 **덩어리 단위**로 짠다. 둘을 한 배열에 섞어
  // 빈 문자열을 걸러내면 자리를 비우려고 넣은 빈 줄까지 함께 사라진다(실제로 그랬다 —
  // 제목과 첫 문장이 붙어 버렸다). 그래서 이어 붙이는 규칙을 나눠 둔다.
  const head = [
    `# ${facts.company} — ${facts.period}`,
    '',
    '아래는 공시 원문에서 뽑은 자료입니다. 읽는 법을 먼저 밝힙니다.',
    '',
    '- **재무 수치는 공시 원자료(XBRL)에서 직접 계산한 값**입니다. 그대로 믿고 쓰셔도 됩니다.',
    '- **사업·위험·경쟁 서술은 AI 가 보고서 원문을 읽고 정리한 해석**입니다. 원문과 다를 수 있습니다.',
    '- 수치가 적히지 않은 항목은 **일부러 뺀 것**입니다. 비어 있다고 지어내지 마세요.',
    ...(facts.sourceUrl ? [`- 원문: ${facts.sourceUrl}`] : []),
  ].join('\n')

  // 자료가 없는 구획은 `section` 이 빈 문자열을 돌려준다. 그런 것만 걸러낸다.
  const blocks = [
    section('이 회사가 무엇으로 버는가', facts.oneLiner),
    section('사업', facts.businessSummary),
    section('돈의 흐름', moneyFlowText(facts)),
    section(
      '사업 부문',
      facts.segments.length > 0
        ? bullets(facts.segments.map((s) => (s.what ? `${s.name} — ${s.what}` : s.name)))
        : null,
    ),
    section('재무 (공시 원자료에서 계산)', financialTable(facts)),
    section('위험 (보고서에서 추린 것)', facts.risks.length > 0 ? riskText(facts.risks) : null),
    section(
      '경영진이 실적의 원인으로 든 것',
      facts.mdnaPoints.length > 0 ? bullets(facts.mdnaPoints) : null,
    ),
    section('경쟁 구도', facts.moat),
    section(
      '보고서가 이름을 댄 경쟁사',
      facts.competitors.length > 0 ? facts.competitors.join(', ') : null,
    ),
    section(
      '이 보고서로는 답이 안 나온 것',
      facts.openQuestions.length > 0 ? bullets(facts.openQuestions) : null,
    ),
  ].filter((block) => block !== '')

  return `${[head, ...blocks, '---', preset.ask].join('\n\n')}\n`
}
