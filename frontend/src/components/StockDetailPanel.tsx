import { useEffect, useState } from 'react'
import { fetchDailyPrices, fetchStockDetail } from '../lib/api'
import type { LiveQuote, MarketState, PricePoint, Quote } from '../lib/api'
import { SECTION_OPTIONS, type Section } from '../lib/useRoute'
import { PriceChart } from './PriceChart'
import { DisclosureList } from './DisclosureList'
import { FinancialSummary } from './FinancialSummary'
import { ValuationBox } from './ValuationBox'
import { PeerComparison } from './PeerComparison'
import { ReportAnalysis } from './ReportAnalysis'
import { SupplyDemand } from './SupplyDemand'
import { StockNotes } from './StockNotes'
import { WatchStar } from './WatchStar'
import {
  changeColor,
  formatBigWon,
  formatChange,
  formatRate,
  formatTimestamp,
  formatVolume,
  formatWon,
} from '../lib/format'
import { Card } from './ui/Card'
import { Segmented } from './ui/Segmented'
import { Skeleton } from './ui/Skeleton'
import { ErrorBox } from './ui/Status'

// 국내 종목 상세.
//
// **한 기둥에 카드 11개를 쌓아 두던 화면이었다.** 배당수익률을 보려면 차트와 수급과
// 메모를 지나 내려가야 했고, 카드마다 따로 로딩이 돌아 종목을 바꿀 때마다 화면이 출렁였다.
//
// 세 묶음으로 나눈다 — 시세를 보러 왔는가(개요) · 숫자를 보러 왔는가(재무) ·
// 회사가 뭐라고 썼는지 보러 왔는가(공시·분석). 온 목적이 셋 중 하나라서 이렇게 갈린다.
//
// **종목 이름과 현재가는 섹션 밖에 둔다.** 어느 묶음을 보고 있든 지금 얼마인지는
// 늘 보여야 한다. 재무를 읽다가 가격을 확인하려고 섹션을 되돌리게 만들지 않는다.
//
// **화면 구조를 먼저 그리고 값을 나중에 채운다.** 예전에는 자료가 도착할 때까지
// "불러오는 중…" 한 줄만 있다가 카드가 통째로 솟아올랐다. 이제는 카드 자리를 미리
// 잡아 두고(`Skeleton`) 그 안만 바뀐다 — 종목을 연달아 눌러도 화면이 출렁이지 않는다.
//
// 미국(`UsDetailPanel`)도 같은 구조다. 담기는 값은 달라도 뼈대가 다르면 탭을 옮길 때마다
// 다른 규칙을 익혀야 한다.

type Props = {
  symbol: string
  /** 목록이 이미 아는 종목명. 상세를 받기 전에도 제목이 비지 않게 한다. */
  name?: string
  /** 목록과 같은 폴링에서 나온 현재가. 상세 화면이 따로 토스를 부르지 않는다. */
  live: LiveQuote | undefined
  market: MarketState | null
  section: Section
  onSection: (next: Section) => void
}

const CHART_DAYS = 90

export function StockDetailPanel({ symbol, name, live, market, section, onSection }: Props) {
  const [latest, setLatest] = useState<Quote | null>(null)
  const [points, setPoints] = useState<PricePoint[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    // 이전 종목의 숫자를 새 종목 이름 아래 남겨 두지 않는다. 잠깐이라도 다른 회사의
    // 종가가 이 회사 것처럼 보이면 안 된다.
    setLatest(null)
    setPoints([])
    setError(null)

    Promise.all([fetchStockDetail(symbol), fetchDailyPrices(symbol, CHART_DAYS)])
      .then(([quote, pointsResult]) => {
        if (cancelled) return
        setLatest(quote)
        setPoints(pointsResult)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })

    // 종목을 빠르게 바꾸면 이전 요청이 늦게 도착해 화면을 덮어쓸 수 있다. 그것을 막는다.
    return () => {
      cancelled = true
    }
  }, [symbol])

  if (error) {
    return <ErrorBox tone="block">{error}</ErrorBox>
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-xl font-semibold">{latest?.name ?? name ?? symbol}</h2>
        <WatchStar symbol={symbol} />
        <span className="tabular text-sm text-neutral-500">
          {symbol}
          {latest ? ` · ${latest.market}` : ''}
        </span>
      </div>

      {/* 현재가와 확정 종가를 나란히 둔다. 둘의 기준 시점이 다르다는 것을 화면에서 드러낸다. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Card
          title={
            <span className="inline-flex items-center gap-1.5">
              현재가
              {market?.is_live && (
                <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
              )}
            </span>
          }
          bodyClassName="px-3 py-3"
        >
          {live ? (
            <>
              <div className="tabular text-2xl font-semibold">
                {formatWon(Number(live.last_price))}
                <span className="ml-1 text-base font-normal text-neutral-400">원</span>
              </div>
              <div
                className={`tabular mt-1 text-sm ${
                  live.change_rate ? changeColor(live.change_rate) : 'text-neutral-500'
                }`}
              >
                {live.change !== null && live.change_rate !== null
                  ? `${formatChange(live.change)} (${formatRate(live.change_rate)})`
                  : '기준가 없음'}
              </div>
              {/* 기준가가 어느 날 종가인지 반드시 밝힌다. 확정 종가는 하루 늦게 올라오므로
                  "어제 대비"가 아니라 "그저께 대비"인 구간이 매일 생긴다. */}
              <div className="mt-2 text-xs text-neutral-500">
                {market?.label ?? ''} · 체결 {formatTimestamp(live.timestamp)}
              </div>
              {live.base_date && (
                <div className="text-xs text-neutral-500">
                  {live.base_date} 종가 {formatWon(Number(live.base_price))}원 대비
                </div>
              )}
            </>
          ) : (
            <Skeleton rows={4} label="현재가를 받는 중…" />
          )}
        </Card>

        <Card
          title="확정 종가"
          hint={latest ? `KRX ${latest.trade_date}` : undefined}
          bodyClassName="px-3 py-3"
        >
          {latest ? (
            <>
              <div className="tabular text-2xl font-semibold">
                {formatWon(latest.close)}
                <span className="ml-1 text-base font-normal text-neutral-400">원</span>
              </div>
              <div className={`tabular mt-1 text-sm ${changeColor(latest.change_rate)}`}>
                {formatChange(latest.change)} ({formatRate(latest.change_rate)})
              </div>
              <div className="mt-2 text-xs text-neutral-500">
                정규장 종가 · 시간외 제외 · 현재가의 기준가
              </div>
            </>
          ) : (
            <Skeleton rows={4} label="확정 종가를 받는 중…" />
          )}
        </Card>
      </div>

      <Segmented
        size="md"
        label="상세 섹션"
        options={SECTION_OPTIONS}
        value={section}
        onChange={onSection}
      />

      {/* 섹션 안의 카드만 자기 자료를 받는다. 열한 개가 한꺼번에 움직이지 않는다. */}
      {section === 'overview' && (
        <>
          <PriceChart points={points} loading={latest === null} />

          <Card
            title="시세"
            hint={latest?.trade_date}
            bodyClassName="px-3 py-3"
          >
            {latest ? (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
                <Field label="시가" value={`${formatWon(latest.open)}원`} />
                <Field label="고가" value={`${formatWon(latest.high)}원`} />
                <Field label="저가" value={`${formatWon(latest.low)}원`} />
                <Field label="거래량" value={`${formatVolume(latest.volume)}주`} />
                <Field label="거래대금" value={`${formatBigWon(latest.trade_value)}원`} />
                <Field label="시가총액" value={`${formatBigWon(latest.market_cap)}원`} />
              </dl>
            ) : (
              <Skeleton rows={4} label="시세를 받는 중…" />
            )}
          </Card>

          {/* 수급은 시세 옆에 둔다 — 거래량·거래대금과 같은 시장 자료라서 재무보다 위가 자연스럽다. */}
          <SupplyDemand symbol={symbol} />

          {/* 메모는 개요에 둔다. 재무나 공시 뒤로 밀면 눌러 들어가야 해서 안 쓰게 된다. */}
          <StockNotes symbol={symbol} />
        </>
      )}

      {section === 'finance' && (
        <>
          {/* 지표를 재무표 위에 둔다. PER·PBR 을 먼저 보고 그 근거인 추이로 내려가는
              순서가 자연스럽다. */}
          <ValuationBox symbol={symbol} />

          {/* 지표 바로 아래. "이 회사 PER 이 32배"를 보고 나서 "업종은 어떤가"로
              이어지는 순서다. 업종을 모르는 종목에서는 아무것도 그리지 않는다. */}
          <PeerComparison symbol={symbol} />

          <FinancialSummary symbol={symbol} />
        </>
      )}

      {section === 'filings' && (
        <>
          {/* 미국 화면과 같은 순서 — 분석이 먼저, 원문 목록이 뒤. */}
          <ReportAnalysis symbol={symbol} />

          <DisclosureList symbol={symbol} />
        </>
      )}
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-neutral-500">{label}</dt>
      <dd className="tabular">{value}</dd>
    </div>
  )
}
