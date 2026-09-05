import type { ReactNode } from 'react'

// 카드 껍데기. 이 마크업이 20 개 파일에 31 번 복붙되어 있었다.
//
// 복붙 자체보다 나쁜 것은 그것들이 조금씩 달라져 있었다는 점이다. 테두리 둥글기가
// rounded 와 rounded-lg 로 갈리고, 본문 여백이 py-2 와 py-4 로 갈리고, 머리글 글자색이
// 파일마다 달랐다. 색 하나 바꾸려면 31 곳을 찾아야 했다.
//
// 머리글은 네 자리로 나뉜다. 지금까지 쓰이던 방식을 그대로 옮긴 것이다.
//   title   "밸류에이션"        — 이 카드가 무엇인가
//   hint    "PER · PBR · 배당"  — 제목 옆 흐린 보충
//   actions 기간 전환·필터 탭   — 제목 바로 뒤에 붙는 조작
//   meta    "2025년" · "불러오는 중…" — 오른쪽 끝으로 밀리는 부가 정보

type CardProps = {
  title?: ReactNode
  hint?: ReactNode
  actions?: ReactNode
  meta?: ReactNode
  /** 본문 좌우 여백을 없앤다. 표를 카드에 통째로 넣을 때 쓴다. */
  flush?: boolean
  /** 본문 여백을 직접 정해야 할 때. 기본은 px-3 py-2. */
  bodyClassName?: string
  className?: string
  children: ReactNode
}

export function Card({
  title,
  hint,
  actions,
  meta,
  flush,
  bodyClassName,
  className = '',
  children,
}: CardProps) {
  const hasHeader = title !== undefined || actions !== undefined || meta !== undefined

  return (
    <div className={`rounded-lg bg-surface shadow-edge ${className}`}>
      {hasHeader && (
        <div className="flex flex-wrap items-center gap-1 border-b border-neutral-800 px-3 py-2">
          {title !== undefined && (
            <span className="mr-1 text-xs text-neutral-400">
              {title}
              {hint !== undefined && <span className="ml-1 text-neutral-600">{hint}</span>}
            </span>
          )}
          {actions}
          {meta !== undefined && <span className="ml-auto text-xs text-neutral-600">{meta}</span>}
        </div>
      )}
      <div className={bodyClassName ?? (flush ? 'py-2' : 'px-3 py-2')}>{children}</div>
    </div>
  )
}
