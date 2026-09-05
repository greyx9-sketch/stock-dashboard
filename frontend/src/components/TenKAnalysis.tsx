import { useEffect, useRef, useState } from 'react'
import { fetchUsAnalysis, runUsAnalysis } from '../lib/api'
import type { UsAnalysis } from '../lib/api'
import { Card } from './ui/Card'
import { DecoderCard } from './analysis/DecoderCard'
import { Skeleton } from './ui/Skeleton'

// 10-K 서술 분석 블록.
//
// 화면을 여는 것만으로는 절대 분석이 돌지 않는다. 열 때는 저장된 결과를 읽기만 하고(GET,
// 무료), 실제 분석은 사용자가 버튼을 눌러야 나간다(POST, 문서당 비용 발생). 백엔드에서
// 메서드로 갈라 둔 구분을 화면에서도 그대로 지킨다.
//
// 결과에 수치가 없는 것은 의도한 것이다. 매출·이익은 위 재무표(XBRL 원자료)가 담당하고
// 여기는 문장 해석만 한다. 그 경계를 사용자가 알 수 있게 안내 문구를 고정으로 붙인다.
//
// 결과를 그리는 일은 `analysis/DecoderCard` 가 맡는다 — 국내 사업보고서 분석과
// 같은 모양이어야 해서 한 곳에 두었다. 여기는 상태(불러오는 중·맡겨 둠·실패)와
// 미국에만 있는 것(회계연도·SEC 원문 링크·잘린 Item)만 다룬다.

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
        {loading && <Skeleton rows={3} label="분석 결과를 확인하는 중…" />}

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

        {/* 밤에 도는 자동 분석이 배치로 맡겨 둔 상태. **실패가 아니라 진행 중**이므로
            다시 시도 버튼을 두지 않는다 — 누르면 반값이 아닌 값으로 한 번 더 사게 된다. */}
        {!loading && !running && !error && analysis?.status === 'pending' && (
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-sm text-neutral-300">
              <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
              자동 분석을 맡겨 두었습니다
            </div>
            <p className="text-xs text-neutral-500">
              값이 반인 대신 결과가 늦게 옵니다. 보통 한 시간 안에, 늦어도 하루 안에
              여기 채워집니다.
            </p>
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
    <DecoderCard
      oneLiner={analysis.one_liner}
      businessSummary={analysis.business_summary}
      segments={analysis.segments}
      realRisks={realRisks}
      boilerplateRisks={boilerplate.map((r) => r.title)}
      mdnaPoints={analysis.mdna_points}
      moat={analysis.moat_and_competition}
      openQuestions={analysis.open_questions}
      riskBadge={() => '실질'}
      scopeNote={
        /* 이 블록이 무엇이고 무엇이 아닌지를 맨 위에 못 박는다. 수치는 재무표가 담당한다. */
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
      }
      footer={
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-neutral-800 pt-2.5 text-[11px] text-neutral-600">
          <span>
            FY{analysis.fiscal_year}
            {analysis.period_end ? ` (${analysis.period_end} 종료)` : ''}
          </span>
          <span>·</span>
          <span>{analysis.filed_date} 제출</span>
          {/* 경영진 논의만 최신 분기에서 온다. 어느 시점 자료인지 밝히지 않으면
              사용자는 카드 전체가 1년 묵은 것으로 읽는다. */}
          {analysis.quarterly_filed_date && (
            <>
              <span>·</span>
              <span className="text-neutral-500">
                경영진 논의는 10-Q ({analysis.quarterly_filed_date} 제출) 기준
              </span>
            </>
          )}
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
      }
    />
  )
}
