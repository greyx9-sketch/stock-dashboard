import type { MoneyFlow } from '../../lib/api'

/* 돈의 흐름도 — 사오는 것 → 값을 붙이는 지점 → 돈을 내는 쪽.
 *
 * ── 왜 도식인가 ───────────────────────────────────────────────────────
 * 카드의 심장은 `one_liner` 한 문장이다. 그런데 한 문장은 **자를 수가 없다.** 화살표로
 * 이으려면 상자가 있어야 하고, 상자가 되려면 항목이어야 한다. 그래서 v4/v5 에서
 * `money_flow` 를 항목으로 따로 받는다. 이 도식은 그 항목을 그대로 놓은 것이다.
 *
 * ── 화살표 방향을 뒤집지 않는다 ───────────────────────────────────────
 * **물건은 오른쪽으로 가고 돈은 왼쪽으로 온다.** 둘을 같은 방향으로 그리면 "고객이
 * 회사에 무엇을 준다"는 그림이 되어 거꾸로 읽힌다. 굵은 화살표로 물건의 흐름을 그리고,
 * 위에 얇은 되돌이 화살표로 돈을 따로 표시한다. 이 도식의 이름이 '돈의 흐름'인데 정작
 * 돈의 방향이 안 보이면 이름값을 못 한다.
 *
 * ── SVG 가 아니라 격자인 이유 ─────────────────────────────────────────
 * 이 프로젝트의 차트는 SVG 로 직접 그린다. 그런데 그것들은 **좌표가 숫자에서 나오는**
 * 그림이고, 이 도식은 **글자 길이가 자리를 정하는** 그림이다. SVG 는 글을 접지 못해서
 * 상자 폭을 글자 수로 어림해야 하고, 실측한 값("모바일AP·메모리(퀄컴·마이크론)")은
 * 부탁한 10자를 훌쩍 넘는다. 격자는 접기를 공짜로 해 주고 좁은 화면에서 세로로
 * 쌓이기까지 한다. 도구를 쓰임에 맞춘 것이지 관례를 깬 것이 아니다.
 *
 * ── 없으면 안 그린다 ──────────────────────────────────────────────────
 * 세 칸 중 하나라도 비면 흐름이 되지 않으므로 도식 자체를 그리지 않는다. 빈 상자를
 * 남겨 두면 "이 회사는 사오는 것이 없다"로 읽힌다. 도식은 글보다 더 사실처럼 보이기
 * 때문에 빈칸이 더 위험하다.
 */

type Props = {
  flow: MoneyFlow
  /** 가운데 상자에 놓을 이름. 없으면 '이 회사'. */
  companyName?: string | null
}

/** 세 칸이 다 차 있어야 흐름이 된다. 호출하는 쪽이 이걸로 그릴지 정한다. */
export function hasMoneyFlow(flow: MoneyFlow | null | undefined): flow is MoneyFlow {
  return Boolean(flow && flow.inputs.length > 0 && flow.engine && flow.revenue_sources.length > 0)
}

export function MoneyFlowDiagram({ flow, companyName }: Props) {
  return (
    <figure className="m-0">
      {/* 돈의 방향. 굵은 화살표(물건)와 **반대**라는 것이 이 도식의 요점이다. */}
      <div
        aria-hidden
        className="mb-1.5 flex items-center gap-2 text-[10px] tracking-wide text-neutral-600"
      >
        <span className="h-px flex-1 bg-neutral-800" />
        <span className="shrink-0">◀ 돈은 이쪽으로 되돌아온다</span>
        <span className="h-px flex-1 bg-neutral-800" />
      </div>

      <div className="grid items-stretch gap-2 lg:grid-cols-[1fr_auto_1fr_auto_1fr]">
        <Column label="사와서" note="돈이 나간다">
          {flow.inputs.map((input) => (
            <Box key={input}>{input}</Box>
          ))}
        </Column>

        <Arrow />

        {/* 가운데만 표면을 올린다. 값이 붙는 자리가 어디인지가 이 도식의 답이다. */}
        <Column label="값을 붙여" note={companyName ?? '이 회사'} emphasis>
          {/* 높이를 늘리지 않는다. 양옆 칸만큼 늘리면 글 두 줄짜리 상자가 텅 빈 판이
              되어, 값이 붙는 **한 지점**이라는 뜻이 흐려진다. 대신 가운데에 세운다. */}
          <div className="rounded-md border border-neutral-600 bg-surface-raised px-3 py-3 text-[13px] font-medium leading-relaxed text-neutral-100">
            {flow.engine}
          </div>
        </Column>

        <Arrow />

        <Column label="팔아서" note="돈이 들어온다">
          {flow.revenue_sources.map((source) => (
            <Box key={`${source.who}-${source.pays_for}`}>
              <span className="text-neutral-200">{source.who}</span>
              {source.pays_for && (
                <span className="mt-0.5 block text-[11px] leading-relaxed text-neutral-500">
                  {source.pays_for}
                </span>
              )}
            </Box>
          ))}
        </Column>
      </div>

      <figcaption className="mt-2 text-[11px] leading-relaxed text-neutral-600">
        보고서가 밝힌 것만 놓았습니다. 비중·금액은 담지 않습니다 — 그건 재무표의 몫입니다.
      </figcaption>
    </figure>
  )
}

function Column({
  label,
  note,
  emphasis = false,
  children,
}: {
  label: string
  note?: string
  emphasis?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="flex min-w-0 flex-col">
      <div className="mb-1.5 flex flex-wrap items-baseline gap-x-1.5">
        <span
          className={
            emphasis
              ? 'text-[11px] font-medium text-neutral-300'
              : 'text-[11px] font-medium text-neutral-400'
          }
        >
          {label}
        </span>
        {note && <span className="text-[10px] text-neutral-600">{note}</span>}
      </div>
      <div
        className={`flex flex-1 flex-col gap-1.5 ${emphasis ? 'justify-center' : ''}`}
      >
        {children}
      </div>
    </div>
  )
}

function Box({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded border border-neutral-800 bg-neutral-950/60 px-2.5 py-1.5 text-xs leading-relaxed text-neutral-300">
      {children}
    </div>
  )
}

/** 칸 사이의 화살표. 좁은 화면에서는 칸이 세로로 쌓이므로 화살표도 아래를 가리킨다. */
function Arrow() {
  return (
    <div aria-hidden className="flex items-center justify-center text-neutral-600">
      <span className="lg:hidden">▼</span>
      <span className="hidden lg:inline">▶</span>
    </div>
  )
}
