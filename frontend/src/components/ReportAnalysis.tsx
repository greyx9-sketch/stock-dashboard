import { useEffect, useRef, useState } from 'react'
import { fetchKrAnalysis, runKrAnalysis } from '../lib/api'
import type { KrAnalysis } from '../lib/api'
import { Card } from './ui/Card'
import { Skeleton } from './ui/Skeleton'

// 국내 사업보고서 서술 분석 블록. 미국 쪽 TenKAnalysis 와 짝이다.
//
// 화면을 여는 것만으로는 분석이 돌지 않는다. 열 때는 저장된 결과만 읽고(GET, 무료),
// 실제 분석은 버튼을 눌러야 나간다(POST, 보고서당 비용 발생).
//
// 미국판과 다른 점: 국내 보고서에는 위험요인 전용 항목이 없어 보고서 곳곳에서 찾아낸
// 것이다. 어디서 나왔는지(source)를 함께 보여줘야 독자가 원문과 대조할 수 있다.

type Props = {
  symbol: string
}

export function ReportAnalysis({ symbol }: Props) {
  const [analysis, setAnalysis] = useState<KrAnalysis | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)

  // 종목을 바꿨는데 이전 요청의 응답이 뒤늦게 도착해 덮어쓰는 것을 막는다.
  const current = useRef(symbol)

  useEffect(() => {
    current.current = symbol
    setAnalysis(null)
    setError(null)
    setRunning(false)
    setLoading(true)

    void fetchKrAnalysis(symbol)
      .then((r) => {
        if (current.current === symbol) setAnalysis(r)
      })
      .catch((err: Error) => {
        if (current.current === symbol) setError(err.message)
      })
      .finally(() => {
        if (current.current === symbol) setLoading(false)
      })
  }, [symbol])

  // 몇 분씩 걸리는 작업이라 진행 표시가 없으면 멈춘 것처럼 보인다.
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
      const result = await runKrAnalysis(symbol, force)
      if (current.current === symbol) setAnalysis(result)
    } catch (err) {
      if (current.current === symbol) setError((err as Error).message)
    } finally {
      if (current.current === symbol) setRunning(false)
    }
  }

  return (
    <Card
      title="사업보고서 분석"
      hint="사업 · 위험 · 경영진단"
      bodyClassName=""
      meta={
        analysis?.status === 'ok' && analysis.fiscal_year ? (
          <span className="tabular">{analysis.fiscal_year}년</span>
        ) : undefined
      }
    >

      <div className="px-3 py-3">
        {loading && <Skeleton rows={3} label="분석 결과를 확인하는 중…" />}

        {!loading && running && (
          <div className="space-y-1.5 py-2">
            <div className="flex items-center gap-2 text-sm text-neutral-300">
              <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
              사업보고서를 읽고 있습니다…
            </div>
            <p className="tabular text-xs text-neutral-500">
              {elapsed}초 경과 · 보통 1~3분 걸립니다
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
              최신 사업보고서의 사업 내용 · 위험 · 경영진단을 읽고 정리합니다.
              <br />
              원문이 수 MB 라 1~3분 걸립니다.
            </p>
            <button
              type="button"
              onClick={() => void run(false)}
              className="rounded border border-neutral-700 bg-neutral-800/60 px-3 py-1.5 text-xs text-neutral-200 transition-colors hover:bg-neutral-800"
            >
              사업보고서 분석하기
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

function AnalysisBody({ analysis }: { analysis: KrAnalysis }) {
  return (
    <div className="space-y-4 text-sm">
      {/* 이 블록이 무엇이고 무엇이 아닌지를 맨 위에 못 박는다. 수치는 재무표가 담당한다. */}
      <p className="rounded border border-neutral-800 bg-neutral-950/50 px-2.5 py-2 text-[11px] leading-relaxed text-neutral-500">
        AI 가 사업보고서 원문을 읽고 정리한 <strong className="text-neutral-400">해석</strong>입니다.
        수치는 담지 않습니다 — 매출·이익은 위 재무표(DART 원자료)를 보세요.
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

      {analysis.key_risks.length > 0 && (
        <Section title="위험요인" note="보고서 곳곳에서 찾아낸 것">
          <ul className="space-y-2.5">
            {analysis.key_risks.map((risk) => (
              <li key={risk.title}>
                <div className="text-neutral-200">{risk.title}</div>
                <p className="mt-1 text-xs leading-relaxed text-neutral-400">
                  {risk.why_it_matters}
                </p>
                {/* 국내 보고서는 위험이 흩어져 있어 출처를 밝혀야 원문과 대조할 수 있다. */}
                <p className="mt-1 text-[11px] text-neutral-600">출처: {risk.source}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {analysis.mdna_points.length > 0 && (
        <Section title="경영진 설명" note="실적·전망의 근거로 회사가 든 것">
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
        <span>{analysis.report_name}</span>
        {analysis.received_date && (
          <>
            <span>·</span>
            <span>{analysis.received_date} 접수</span>
          </>
        )}
        {analysis.source_url && (
          <>
            <span>·</span>
            {/* DART 원문. 해석이 미덥지 않으면 바로 대조할 수 있어야 한다. */}
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
