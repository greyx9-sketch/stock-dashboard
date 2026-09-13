import { useMemo, useRef, useState } from 'react'
import { PRESETS, buildPrompt } from '../../lib/promptText'
import type { PromptFacts, PromptPreset } from '../../lib/promptText'

/* 이어서 물어보기 — 이 보고서를 claude.ai 에 붙여넣을 프롬프트로 뽑는다.
 *
 * ── 왜 카드 맨 끝인가 ─────────────────────────────────────────────────
 * 바로 위가 "아직 모르는 것"이다. 보고서를 다 읽고 남은 질문을 본 그 자리가, 자연스럽게
 * "그럼 이건 어디서 알아보지"가 되는 자리다. 위에 놓으면 읽기도 전에 나가라는 말이 된다.
 *
 * ── 복사가 막히는 사이트다 ────────────────────────────────────────────
 * **이 사이트는 HTTP 다**(도메인을 사지 않기로 했다). `navigator.clipboard` 는 보안
 * 맥락(HTTPS·localhost)에서만 동작하므로 배포된 사이트에서는 없거나 거부된다.
 * 개발 PC 의 localhost 에서만 되고 진짜 사이트에서는 안 되는, 눈치채기 어려운 종류의
 * 고장이다. 그래서 셋을 겹쳐 둔다.
 *
 *   1. `navigator.clipboard` 가 있으면 그걸 쓴다 (나중에 HTTPS 를 붙이면 이 길로 간다)
 *   2. 없으면 `document.execCommand('copy')` — 낡았지만 HTTP 에서 동작한다
 *   3. 둘 다 실패하면 **글상자를 펴서 직접 고르게 한다.** 복사가 안 된다고만 하면
 *      사용자는 할 수 있는 게 없다
 *
 * ── 미리 보여준다 ─────────────────────────────────────────────────────
 * 무엇을 복사했는지 모르는 채로 남의 모델에 붙여넣게 하지 않는다. 접어 두되 펼 수 있게
 * 하고, 글자 수를 같이 밝힌다.
 */

type Props = {
  facts: PromptFacts
}

export function PromptHandoff({ facts }: Props) {
  // 자료가 없어 성립하지 않는 지시는 아예 내놓지 않는다. 경쟁사가 없는데 "경쟁사와
  // 견주기"를 눌러 봐야 받는 쪽이 기억으로 경쟁사를 지어낼 뿐이다.
  const presets = useMemo(
    () => PRESETS.filter((preset) => !preset.requires || preset.requires(facts)),
    [facts],
  )
  const [chosen, setChosen] = useState<PromptPreset>(presets[0])
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState<'yes' | 'manual' | null>(null)
  const areaRef = useRef<HTMLTextAreaElement>(null)

  const prompt = useMemo(() => buildPrompt(facts, chosen), [facts, chosen])

  if (presets.length === 0) return null

  const copy = async () => {
    // 1. 보안 맥락이면 표준 API.
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(prompt)
        setCopied('yes')
        return
      }
    } catch {
      // 권한 거부 등. 아래 낡은 방법으로 내려간다.
    }

    // 2. HTTP 에서도 되는 낡은 방법. 화면 밖 글상자에 담아 고른 뒤 복사한다.
    try {
      const scratch = document.createElement('textarea')
      scratch.value = prompt
      // `display:none` 이면 고를 수 없어 복사도 안 된다. 화면 밖으로 치운다.
      scratch.style.position = 'fixed'
      scratch.style.top = '-1000px'
      scratch.setAttribute('readonly', '')
      document.body.appendChild(scratch)
      scratch.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(scratch)
      if (ok) {
        setCopied('yes')
        return
      }
    } catch {
      // 아래로 내려간다.
    }

    // 3. 둘 다 막혔다. 글상자를 펴고 전체를 골라 둔다 — 사용자가 Ctrl+C 만 누르면 된다.
    setOpen(true)
    setCopied('manual')
    window.setTimeout(() => {
      areaRef.current?.focus()
      areaRef.current?.select()
    }, 0)
  }

  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-950/40 p-3">
      <h3 className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-xs font-medium text-neutral-300">이어서 물어보기</span>
        <span className="text-[11px] text-neutral-600">
          이 보고서를 그대로 담은 프롬프트를 복사해 claude.ai 에 붙여넣으세요
        </span>
      </h3>

      <p className="mt-1.5 text-[11px] leading-relaxed text-neutral-500">
        이 카드는 <strong className="text-neutral-400">공시에 적힌 것</strong>만 다룹니다 —
        투자 의견을 내지 않고, 원문 밖 지식으로 보충하지 않으며, 그 뒤의 소식을 모릅니다.
        그 못 하는 것들을 이어서 물어보는 자리입니다.
      </p>

      {/* 무엇을 시킬지 고른다. 고른 것에 따라 자료 뒤에 붙는 지시문만 바뀐다. */}
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            onClick={() => {
              setChosen(preset)
              setCopied(null)
            }}
            aria-pressed={chosen.id === preset.id}
            title={preset.hint}
            className={
              chosen.id === preset.id
                ? 'rounded border border-neutral-500 bg-surface-raised px-2 py-1 text-[11px] text-neutral-100'
                : 'rounded border border-neutral-800 px-2 py-1 text-[11px] text-neutral-400 transition-colors hover:border-neutral-700 hover:text-neutral-200'
            }
          >
            {preset.label}
          </button>
        ))}
      </div>
      <p className="mt-1.5 text-[11px] text-neutral-600">{chosen.hint}</p>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={copy}
          className="rounded-md bg-neutral-100 px-3 py-1.5 text-xs text-neutral-900 transition-colors hover:bg-white"
        >
          프롬프트 복사
        </button>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="rounded px-1 py-0.5 text-[11px] text-neutral-500 transition-colors hover:text-neutral-300"
        >
          {open ? '접기' : '무엇이 복사되는지 보기'}
        </button>
        <span className="tabular text-[10px] text-neutral-600">
          {prompt.length.toLocaleString('ko-KR')}자
        </span>
        {/* 결과는 소리 내어 읽히게 한다(role=status). 색만으로 알리지 않는다. */}
        {copied === 'yes' && (
          <span role="status" className="text-[11px] text-neutral-400">
            복사했습니다
          </span>
        )}
        {copied === 'manual' && (
          <span role="status" className="text-[11px] text-amber-400/90">
            브라우저가 복사를 막았습니다 — 아래 글이 선택돼 있으니 Ctrl+C 를 누르세요
          </span>
        )}
      </div>

      {open && (
        <textarea
          ref={areaRef}
          readOnly
          value={prompt}
          rows={14}
          onFocus={(event) => event.currentTarget.select()}
          className="mt-2 w-full resize-y rounded-md border border-neutral-800 bg-neutral-950 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-neutral-300"
        />
      )}
    </section>
  )
}
