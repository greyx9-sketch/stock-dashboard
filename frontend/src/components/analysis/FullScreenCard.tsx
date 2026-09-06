import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

/* 해독 카드를 넓게 펴 놓는 화면.
 *
 * ── 왜 필요했나 ───────────────────────────────────────────────────────
 * 상세 패널은 550px 이다. 표와 나란히 놓으려고 그렇게 잡은 폭인데, 해독 카드처럼
 * **읽어야 하는 글**에는 좁다. 한 줄에 스무 자쯤 들어가서 문장이 계단처럼 접힌다.
 * 사용자가 "가독성을 위해서 새 창으로 봤으면 좋겠다"고 한 것이 이것이다.
 *
 * ── 왜 상태가 아니라 주소인가 ─────────────────────────────────────────
 * `useRoute` 에 `expanded` 를 두어 `#/kr/005930/filings/card` 로 만들었다.
 * 화면 상태로 들고 있었으면 셋을 잃는다 — 링크로 보내기, 새 탭으로 열기,
 * 뒤로가기로 닫기. 이 앱은 처음부터 "주소가 화면을 들고 있다"로 지어졌다.
 *
 * 그래서 여는 단추도 <button> 이 아니라 <a href="#..."> 다. 오른쪽 눌러
 * "새 탭에서 열기" 를 하면 진짜 새 창이 된다.
 *
 * ── 덮개인 이유 ───────────────────────────────────────────────────────
 * 화면을 갈아 끼우지 않고 위에 덮는다. 목록의 스크롤 위치와 고른 종목이 그대로
 * 남아서, 닫으면 보던 자리로 정확히 돌아온다.
 *
 * ── 읽기 폭 ───────────────────────────────────────────────────────────
 * 본문을 `max-w-3xl`(768px)로 묶는다. 화면이 아무리 넓어도 한 줄이 길어지면
 * 눈이 다음 줄 첫머리를 못 찾는다. 카드 자체는 그보다 넓게 두어 표와 격자가
 * 숨 쉴 자리를 준다.
 */

type Props = {
  /** 머리글에 크게 놓일 종목 이름. */
  title: string
  /** 이름 옆 작은 글씨(티커·시장). */
  subtitle?: ReactNode
  onClose: () => void
  children: ReactNode
}

export function FullScreenCard({ title, subtitle, onClose, children }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  // 열릴 때 닫기 단추에 포커스를 준다. 이걸 안 하면 키보드로 연 사람의 포커스가
  // 덮개 뒤 페이지에 그대로 남아, Tab 을 눌러도 덮개 안으로 들어오지 못한다.
  useEffect(() => {
    closeRef.current?.focus()
  }, [])

  // 덮개가 떠 있는 동안 뒤 페이지가 스크롤되지 않게 한다. 그러지 않으면 카드 끝에서
  // 계속 굴렸을 때 뒤에 있는 목록이 움직인다(스크롤 체이닝).
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  // Esc 로 닫는다. 덮개를 여는 방법이 여럿이어도 닫는 방법은 늘 같아야 한다.
  //
  // Tab 이 덮개 밖으로 새어 나가는 것도 여기서 막는다. 진짜 포커스 가둠(focus trap)은
  // 라이브러리를 들이지 않고는 완전하게 만들기 어렵지만, 끝에서 처음으로 돌려보내는
  // 것만으로 실제 쓰임의 대부분이 덮인다.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !panelRef.current) return

      const focusable = panelRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-label={`${title} 기업 해독 카드`}
      // 배경을 불투명하게 둔다. 반투명이면 뒤의 표와 배경 격자가 글자 뒤로 비쳐
      // 읽기가 나빠진다 — 넓게 펴는 목적과 정면으로 어긋난다.
      className="fixed inset-0 z-50 overflow-y-auto bg-neutral-950"
    >
      <div className="sticky top-0 z-10 border-b border-neutral-800 bg-neutral-950/95 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center gap-3 px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold text-neutral-100">{title}</h2>
            {subtitle && <div className="mt-0.5 text-xs text-neutral-500">{subtitle}</div>}
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="ml-auto shrink-0 rounded border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800"
          >
            닫기 <span className="text-neutral-600">Esc</span>
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-4xl px-4 py-5">{children}</div>
    </div>
  )
}
