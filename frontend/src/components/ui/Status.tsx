import type { ReactNode } from 'react'

// 기다리는 중 · 실패 · 비어 있음. 세 가지 상태 표시를 한 파일에 모았다.
//
// 흩어져 있을 때의 문제는 개수가 아니라 **같은 뜻이 다른 모양으로 나왔다**는 것이다.
// 실패가 red 로 4 곳, rose 로 2 곳이었고 테두리 둥글기·여백·글자 크기까지 달랐다.
// 사용자는 그 둘이 다른 종류의 문제라고 읽게 된다.
//
// 스크린리더 대응도 여기 한 곳에서 끝난다. 지금까지는 실패해도 아무 알림이 없었다.

/** 기다리는 중. 화면에 이미 값이 있으면 그 옆에, 없으면 자리를 채워 보여준다. */
export function Loading({
  label,
  hint,
  className = '',
}: {
  /** 무엇을 기다리는지 목적어를 준다. "재무를 받는 중" 처럼. */
  label: string
  /** 왜 오래 걸리는지. "처음 보는 종목은 십여 초 걸립니다" */
  hint?: ReactNode
  className?: string
}) {
  return (
    <p aria-live="polite" aria-busy="true" className={`text-xs text-neutral-500 ${className}`}>
      {label}
      {hint !== undefined && <span className="ml-1 text-neutral-600">{hint}</span>}
    </p>
  )
}

/** 실패. block 은 화면 상단을 가로지르는 상자, inline 은 카드 안 한 줄. */
export function ErrorBox({
  children,
  tone = 'inline',
  onRetry,
  retryLabel = '다시 시도',
  className = '',
}: {
  children: ReactNode
  tone?: 'inline' | 'block'
  onRetry?: () => void
  retryLabel?: string
  className?: string
}) {
  if (tone === 'block') {
    return (
      <div
        role="alert"
        className={`rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300 ${className}`}
      >
        {children}
        {onRetry && <RetryButton onClick={onRetry} label={retryLabel} />}
      </div>
    )
  }
  return (
    <p role="alert" className={`text-xs text-red-300 ${className}`}>
      {children}
      {onRetry && <RetryButton onClick={onRetry} label={retryLabel} />}
    </p>
  )
}

function RetryButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="ml-2 rounded border border-neutral-700 px-2 py-0.5 text-xs text-neutral-300 transition-colors hover:bg-neutral-800"
    >
      {label}
    </button>
  )
}

/**
 * 화면이 바뀌었다는 것을 소리로만 알린다. 눈에는 보이지 않는다.
 *
 * 목록은 눈으로 보면 바뀐 것이 대번에 보이지만, 화면을 읽어 주는 프로그램을 쓰면
 * **아무 일도 안 일어난 것과 구분되지 않는다.** 검색어를 넣어도, 시장 필터를 눌러도
 * 아무 말이 없었다. 몇 건이 나왔는지 알려면 표를 처음부터 다시 훑어야 했다.
 *
 * `role="status"` 는 읽던 것을 끊지 않고 사이에 끼워 읽는다(polite). 시세처럼 계속
 * 바뀌는 값에 쓰면 말이 끊이지 않으므로 **사용자가 뭔가를 눌러서 목록이 바뀐 때만** 쓴다.
 *
 * 이 상자는 항상 화면에 있어야 한다 — 없다가 생기면 그 변화를 못 알아채는 브라우저가
 * 있다. 그래서 받는 중일 때는 빈 문자열을 넘긴다.
 */
export function Announce({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="sr-only">
      {children}
    </p>
  )
}

/** 비어 있음. 실패가 아니다 — 조건에 맞는 것이 없거나 아직 자료가 없는 경우다. */
export function Empty({
  title,
  hint,
  className = '',
}: {
  title: string
  /** 왜 비었는지, 무엇을 하면 되는지. 이 프로젝트는 "—" 대신 이유를 적어 왔다. */
  hint?: ReactNode
  className?: string
}) {
  return (
    <div className={`text-xs text-neutral-500 ${className}`}>
      <p>{title}</p>
      {hint !== undefined && <p className="mt-1 text-neutral-600">{hint}</p>}
    </div>
  )
}
