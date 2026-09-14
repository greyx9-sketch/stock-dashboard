import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchKrPrompt, fetchPromptPresets, fetchUsPrompt } from '../lib/api'
import type { PromptPreset, ResearchPrompt as Prompt } from '../lib/api'
import { Card } from './ui/Card'
import { Skeleton } from './ui/Skeleton'

/* 공시·분석 자리 — **AI 에게 넘길 리서치 지시서**.
 *
 * ── 무엇이 바뀌었나 (2026-09-14) ──────────────────────────────────────
 * 여기는 원래 우리가 Anthropic API 로 공시를 분석해 카드로 보여주던 자리다. 그 경로를
 * 걷어내고 **지시서 한 장**으로 바꿨다. 사용자의 결정이고, 이유가 둘이다.
 *
 *   1. **돈.** 분석 한 건에 200~410원이 들었다(실측, 7건에 2,366원). 구독이 있는
 *      claude.ai 에 붙여넣으면 추가 비용이 0원이다.
 *   2. **더 정확하다.** 우리 API 분석은 "원문에 없는 것을 쓰지 마라"가 첫째 규칙이라
 *      최근 뉴스도 업황도 모른다 — 일부러 그렇게 만든 것이다. 붙여넣는 쪽은 웹을
 *      뒤지고 원문 링크를 직접 열어 볼 수 있다.
 *
 * 그래서 이 화면에는 **해석이 한 줄도 없다.** 숫자와 원문 주소와 시킬 일뿐이다.
 *
 * ── 복사가 막히는 사이트다 ────────────────────────────────────────────
 * **이 사이트는 HTTP 다**(도메인을 사지 않기로 했다). `navigator.clipboard` 는 보안
 * 맥락에서만 동작하므로 배포된 사이트에서는 **아예 없다**(실측: `undefined`).
 * 개발 PC 의 localhost 에서만 되고 진짜 사이트에서는 안 되는, 눈치채기 어려운 고장이다.
 * 그래서 셋을 겹친다: 표준 API → `execCommand` → 글상자를 펴서 전체 선택.
 */

type Props = {
  symbol: string
  market: 'KR' | 'US'
}

export function ResearchPrompt({ symbol, market }: Props) {
  const [presets, setPresets] = useState<PromptPreset[]>([])
  const [chosen, setChosen] = useState<string | null>(null)
  const [prompt, setPrompt] = useState<Prompt | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<'yes' | 'manual' | null>(null)
  const areaRef = useRef<HTMLTextAreaElement>(null)
  const resetTimer = useRef<number | null>(null)

  /* 눌렀다는 표시를 **단추 위에서** 하고 잠시 뒤 되돌린다.
   *
   * 처음에는 단추 옆에 "복사했습니다"를 띄웠는데 사용자가 "눌렸는지 모르겠다"고 했다.
   * 둘 다 틀렸던 것이다 —
   *   1. 눈은 **단추**를 보고 있는데 표시는 그 옆 11px 회색 글씨였다.
   *   2. 한 번 뜬 표시가 사라지지 않아서 **두 번째로 누르면 변화가 0** 이었다.
   * 그래서 되돌리는 타이머를 둔다. 다시 누르면 다시 바뀌어야 눌린 줄 안다. */
  const flash = (kind: 'yes' | 'manual') => {
    setCopied(kind)
    if (resetTimer.current) window.clearTimeout(resetTimer.current)
    // 실패 안내는 읽어야 하는 글이라 더 오래 둔다.
    resetTimer.current = window.setTimeout(
      () => setCopied(null),
      kind === 'yes' ? 2000 : 8000,
    )
  }

  // 화면을 떠난 뒤 타이머가 남아 state 를 건드리지 않게 한다.
  useEffect(() => {
    return () => {
      if (resetTimer.current) window.clearTimeout(resetTimer.current)
    }
  }, [])

  // 지시서 종류는 서버가 들고 있다. 프롬프트 본문과 같은 곳에 있어야 둘이 어긋나지 않는다.
  useEffect(() => {
    let cancelled = false
    void fetchPromptPresets()
      .then((list) => {
        if (cancelled) return
        setPresets(list)
        setChosen((current) => current ?? list[0]?.id ?? null)
      })
      .catch(() => !cancelled && setPresets([]))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!chosen) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setCopied(null)

    const load = market === 'KR' ? fetchKrPrompt : fetchUsPrompt
    void load(symbol, chosen)
      .then((result) => !cancelled && setPrompt(result))
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))

    return () => {
      cancelled = true
    }
  }, [symbol, market, chosen])

  const current = useMemo(
    () => presets.find((preset) => preset.id === chosen) ?? null,
    [presets, chosen],
  )

  const copy = async () => {
    const text = prompt?.text
    if (!text) return

    // 1. 보안 맥락이면 표준 API. HTTPS 를 붙이는 날 이 길로 간다.
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
        flash('yes')
        return
      }
    } catch {
      // 권한 거부 등. 아래로 내려간다.
    }

    // 2. HTTP 에서도 되는 낡은 방법. `display:none` 이면 고를 수 없어 복사도 안 되므로
    //    화면 밖으로 치운 글상자를 쓴다.
    try {
      const scratch = document.createElement('textarea')
      scratch.value = text
      scratch.style.position = 'fixed'
      scratch.style.top = '-1000px'
      scratch.setAttribute('readonly', '')
      document.body.appendChild(scratch)
      scratch.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(scratch)
      if (ok) {
        flash('yes')
        return
      }
    } catch {
      // 아래로 내려간다.
    }

    // 3. 둘 다 막혔다. 전체를 골라 둔다 — 사용자가 Ctrl+C 만 누르면 된다.
    flash('manual')
    window.setTimeout(() => {
      areaRef.current?.focus()
      areaRef.current?.select()
    }, 0)
  }

  return (
    <Card
      title="AI 분석 지시서"
      hint="복사해 claude.ai 에 붙여넣으세요"
      meta={
        prompt ? (
          <span className="tabular">{prompt.text.length.toLocaleString('ko-KR')}자</span>
        ) : undefined
      }
      bodyClassName=""
    >
      <div className="space-y-3 px-3 py-3">
        <p className="text-[11px] leading-relaxed text-neutral-500">
          이 글에는 <strong className="text-neutral-400">해석이 한 줄도 없습니다.</strong>{' '}
          공시 원자료에서 계산한 숫자와 공시 원문 주소, 그리고 조사 지시뿐입니다. 붙여넣으면
          AI 가 원문을 직접 열어 읽고 웹까지 찾아 보고서를 씁니다.
        </p>

        {/* 무엇을 시킬지 고른다. 자료는 같고 시키는 일만 바뀐다. */}
        {presets.length > 0 && (
          <div>
            <div className="flex flex-wrap gap-1.5">
              {presets.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => setChosen(preset.id)}
                  aria-pressed={preset.id === chosen}
                  className={
                    preset.id === chosen
                      ? 'rounded border border-neutral-500 bg-surface-raised px-2 py-1 text-[11px] text-neutral-100'
                      : 'rounded border border-neutral-800 px-2 py-1 text-[11px] text-neutral-400 transition-colors hover:border-neutral-700 hover:text-neutral-200'
                  }
                >
                  {preset.label}
                </button>
              ))}
            </div>
            {current && <p className="mt-1.5 text-[11px] text-neutral-600">{current.hint}</p>}
          </div>
        )}

        {loading && <Skeleton rows={4} label="지시서를 만드는 중…" />}
        {error && (
          <p role="alert" className="text-xs leading-relaxed text-red-400">
            {error}
          </p>
        )}

        {prompt && !loading && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {/* 눌렸다는 것이 **단추 위에서** 보여야 한다. 글자와 바탕색이 같이 바뀌고,
                  2초 뒤 되돌아온다 — 되돌아와야 다음에 눌렀을 때도 변화가 보인다.
                  글자 수가 달라 단추가 들썩이지 않게 최소 폭을 준다. */}
              <button
                type="button"
                onClick={copy}
                /* 색이 아니라 **밝기를 뒤집어** 알린다. 초록은 미국식 상승과 겹치고
                   빨강·파랑은 이 화면에서 이미 상승·하락이다(포커스 링을 무채색으로
                   둔 것과 같은 이유). 밝은 단추가 어두워지는 것은 뜻이 없는 변화라
                   시세 숫자 옆에서 방향으로 오독될 일이 없다. */
                className={`min-w-[92px] rounded-md px-3 py-1.5 text-xs transition-colors ${
                  copied === 'yes'
                    ? 'bg-neutral-700 text-neutral-100'
                    : 'bg-neutral-100 text-neutral-900 hover:bg-white'
                }`}
              >
                {copied === 'yes' ? '복사됨 ✓' : '복사'}
              </button>
              <a
                href="https://claude.ai/new"
                target="_blank"
                rel="noreferrer"
                className="rounded px-1 py-0.5 text-[11px] text-neutral-500 underline-offset-2 transition-colors hover:text-neutral-300 hover:underline"
              >
                claude.ai 열기 ↗
              </a>
              {/* 화면 낭독기용. 색과 글자 변화만으로는 눈으로 보는 사람에게만 전해진다. */}
              <span role="status" className="sr-only">
                {copied === 'yes' ? '프롬프트를 복사했습니다' : ''}
              </span>
              {copied === 'manual' && (
                <span role="status" className="text-[11px] text-amber-400/90">
                  브라우저가 복사를 막았습니다 — 아래 글이 선택돼 있으니 Ctrl+C 를 누르세요
                </span>
              )}
            </div>

            {/* 무엇이 담겼는지 밝힌다. 붙여넣기 전에 눈으로 확인할 수 있어야 한다. */}
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-neutral-600">
              {prompt.included.map((item) => (
                <span key={item} className="rounded bg-neutral-800/70 px-1.5 py-0.5">
                  {item}
                </span>
              ))}
              {prompt.missing.map((item) => (
                <span
                  key={item}
                  title="이 자료는 담지 못했습니다"
                  className="rounded border border-amber-500/30 px-1.5 py-0.5 text-amber-400/80"
                >
                  {item} 없음
                </span>
              ))}
            </div>

            {/* 접지 않고 그대로 보여준다. 이 화면의 내용물이 이것 하나뿐이라,
                접어 두면 빈 화면처럼 보인다. */}
            <textarea
              ref={areaRef}
              readOnly
              value={prompt.text}
              rows={18}
              onFocus={(event) => event.currentTarget.select()}
              className="w-full resize-y rounded-md border border-neutral-800 bg-neutral-950 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-neutral-300"
            />
          </>
        )}
      </div>
    </Card>
  )
}
