import { useEffect, useRef, useState } from 'react'
import { fetchUsAnalysis, runUsAnalysis } from '../lib/api'
import type { UsAnalysis } from '../lib/api'
import { Card } from './ui/Card'

// 10-K 서술 분석 블록.
//
// 화면을 여는 것만으로는 절대 분석이 돌지 않는다. 열 때는 저장된 결과를 읽기만 하고(GET,
// 무료), 실제 분석은 사용자가 버튼을 눌러야 나간다(POST, 문서당 비용 발생). 백엔드에서
// 메서드로 갈라 둔 구분을 화면에서도 그대로 지킨다.
//
// 결과에 수치가 없는 것은 의도한 것이다. 매출·이익은 위 재무표(XBRL 원자료)가 담당하고
// 여기는 문장 해석만 한다. 그 경계를 사용자가 알 수 있게 안내 문구를 고정으로 붙인다.

type Props = {
  ticker: string
}

const RUN_HINT = '10-K 본문을 읽어야 해서 30초~2분 걸립니다.'

export function TenKAnalysis({ ticker }: Props) {
  const [analysis, setAnalysis] = useState<UsAnalysis | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)

  // 종목을 바꿨는데 이전 요청의 응답이 뒤늦게 도착해 덮어쓰는 것을 막는다.
  const currentTicker = useRef(ticker)

  useEffect(() => {
    currentTicker.current = ticker
    setAnalysis(null)
    setError(null)
    setRunning(false)
    setLoading(true)

    void fetchUsAnalysis(ticker)
      .then((result) => {
        if (currentTicker.current === ticker) setAnalysis(result)
      })
      .catch((err: Error) => {
        if (currentTicker.current === ticker) setError(err.message)
      })
      .finally(() => {
        if (currentTicker.current === ticker) setLoading(false)
      })
  }, [ticker])

  // 분석이 도는 동안 경과 시간을 보여 준다. 몇 십 초씩 걸리는 작업이라
  // 진행 표시가 없으면 멈춘 것처럼 보인다.
  useEffect(() => {
    if (!running) return
    setElapsed(0)
    const timer = window.setInterval(() => setElapsed((n) => n + 1), 1000)
    return () => window.clearInterval(timer)
  }, [running])

  async function run(force: boolean) {
    setRunning(true)
    setError(null)
    try {
      const result = await runUsAnalysis(ticker, force)
      if (currentTicker.current === ticker) setAnalysis(result)
    } catch (err) {
      if (currentTicker.current === ticker) setError((err as Error).message)
    } finally {
      if (currentTicker.current === ticker) setRunning(false)
    }
  }

  return (
    <Card
      title="10-K 분석"
      hint="사업 · 위험요인 · 경영진 논의"
      bodyClassName=""
      meta={
        analysis?.status === 'ok' ? (
          <span className="tabular">FY{analysis.fiscal_year}</span>
        ) : undefined
      }
    >

      <div className="px-3 py-3">
        {loading && <p className="text-xs text-neutral-500">불러오는 중…</p>}

        {!loading && running && (
          <div className="space-y-1.5 py-2">
            <div className="flex items-center gap-2 text-sm text-neutral-300">
              <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
              10-K 원문을 읽고 있습니다…
            </div>
            <p className="tabular text-xs text-neutral-500">
              {elapsed}초 경과 · 보통 30초~2분 걸립니다
            </p>
          </div>
        )}

        {!loading && !running && error && (
          <div className="space-y-2">
            <p className="whitespace-pre-line text-xs text-amber-400/90">{error}</p>
            <button
              type="button"
              onClick={() => void run(true)}
              className="rounded border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800"
            >
              다시 시도
            </button>
          </div>
        )}

        {!loading && !running && !error && analysis?.status === 'none' && (
          <div className="space-y-2">
            <p className="text-xs text-neutral-500">
              최신 10-K 의 사업 내용 · 위험요인 · 경영진 논의를 읽고 한국어로 정리합니다.
              <br />
              {RUN_HINT}
            </p>
            <button
              type="button"
              onClick={() => void run(false)}
              className="rounded border border-neutral-700 bg-neutral-800/60 px-3 py-1.5 text-xs text-neutral-200 transition-colors hover:bg-neutral-800"
            >
              10-K 분석하기
            </button>
          </div>
        )}

        {!loading && !running && !error && analysis?.status === 'failed' && (
          <div className="space-y-2">
            <p className="whitespace-pre-line text-xs text-amber-400/90">
              {analysis.error ?? '분석에 실패했습니다.'}
            </p>
            <button
              type="button"
              onClick={() => void run(true)}
              className="rounded border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800"
            >
              다시 시도
            </button>
          </div>
        )}

        {!loading && !running && !error && analysis?.status === 'ok' && (
          <AnalysisBody analysis={analysis} />
        )}
      </div>
    </Card>
  )
}

function AnalysisBody({ analysis }: { analysis: UsAnalysis }) {
  const realRisks = analysis.key_risks.filter((r) => !r.is_boilerplate)
  const boilerplate = analysis.key_risks.filter((r) => r.is_boilerplate)

  return (
    <div className="space-y-4 text-sm">
      {/* 이 블록이 무엇이고 무엇이 아닌지를 맨 위에 못 박는다. 수치는 재무표가 담당한다. */}
      <p className="rounded border border-neutral-800 bg-neutral-950/50 px-2.5 py-2 text-[11px] leading-relaxed text-neutral-500">
        AI 가 10-K 원문을 읽고 정리한 <strong className="text-neutral-400">해석</strong>입니다.
        수치는 담지 않습니다 — 매출·이익은 위 재무표(SEC XBRL 원자료)를 보세요.
        {analysis.truncated.length > 0 && (
          <>
            <br />
            {analysis.truncated.join(', ')} 은 분량이 많아 앞부분만 반영됐습니다.
          </>
        )}
      </p>

      <Section title="사업">
        <p className="leading-relaxed text-neutral-300">{analysis.business_summary}</p>
        {analysis.segments.length > 0 && (
          <ul className="mt-2 space-y-1">
            {analysis.segments.map((segment) => (
              <li key={segment} className="flex gap-2 text-xs text-neutral-400">
                <span className="text-neutral-600">·</span>
                <span>{segment}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {realRisks.length > 0 && (
        <Section title="위험요인" note="이 회사에 특유한 것">
          <ul className="space-y-2.5">
            {realRisks.map((risk) => (
              <li key={risk.title}>
                <div className="flex items-baseline gap-2">
                  <span className="mt-px shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-400/90">
                    실질
                  </span>
                  <span className="text-neutral-200">{risk.title}</span>
                </div>
                <p className="mt-1 pl-1 text-xs leading-relaxed text-neutral-400">
                  {risk.why_it_matters}
                </p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {boilerplate.length > 0 && (
        <Section title="형식적 위험" note="모든 보고서에 붙는 정형 문구">
          <ul className="space-y-1">
            {boilerplate.map((risk) => (
              <li key={risk.title} className="flex gap-2 text-xs text-neutral-500">
                <span className="text-neutral-700">·</span>
                <span>{risk.title}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {analysis.mdna_points.length > 0 && (
        <Section title="경영진 설명" note="실적 변화의 원인으로 회사가 든 것">
          <ul className="space-y-1.5">
            {analysis.mdna_points.map((point) => (
              <li key={point} className="flex gap-2 text-xs leading-relaxed text-neutral-400">
                <span className="shrink-0 text-neutral-600">·</span>
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {analysis.moat_and_competition && (
        <Section title="경쟁 구도">
          <p className="text-xs leading-relaxed text-neutral-400">
            {analysis.moat_and_competition}
          </p>
        </Section>
      )}

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-neutral-800 pt-2.5 text-[11px] text-neutral-600">
        <span>
          FY{analysis.fiscal_year}
          {analysis.period_end ? ` (${analysis.period_end} 종료)` : ''}
        </span>
        <span>·</span>
        <span>{analysis.filed_date} 제출</span>
        {analysis.source_url && (
          <>
            <span>·</span>
            {/* SEC 원문. 해석이 미덥지 않으면 바로 대조할 수 있어야 한다. */}
            <a
              href={analysis.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-neutral-500 underline decoration-neutral-700 underline-offset-2 transition-colors hover:text-neutral-300"
            >
              원문 보기
            </a>
          </>
        )}
      </div>
    </div>
  )
}

function Section({
  title,
  note,
  children,
}: {
  title: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-medium text-neutral-400">
        {title}
        {note && <span className="ml-1.5 font-normal text-neutral-600">{note}</span>}
      </h3>
      {children}
    </div>
  )
}
