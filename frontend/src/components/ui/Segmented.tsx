import { useRef } from 'react'

// 서로 배타적인 선택지를 나란히 놓는 버튼 묶음. 화면 다섯 곳에 각각 하드코딩되어 있었다.
//   · 국내 목록의 정렬(시가총액/거래대금/거래량/등락률)과 시장(전체/KOSPI/KOSDAQ)
//   · 재무 카드의 지표(매출/영업이익/순이익)
//   · 공시 카드의 유형 필터 5 개
//   · 재무의 연간↔분기, 3개월↔누적
//
// 접근성이 여기서 한 번에 해결된다. 지금까지는 그냥 <button> 나열이라 스크린리더가
// "이 중 하나를 고르는 것"임을 알 수 없었다. role="group" 과 aria-pressed 를 붙인다.
//
// **두 가지 쓰임이 있고 둘은 다른 물건이다**(3단계에서 갈랐다).
//
//   group  필터·토글. 목록을 거르거나 같은 카드의 표시를 바꾼다. 화면이 갈리지 않는다.
//          지금까지의 동작 그대로 — 버튼마다 탭 정지가 있고 aria-pressed 를 쓴다.
//
//   tabs   화면을 갈아 끼운다. 상단의 국내/미국/관심/분석/일정, 상세의 개요/재무/공시·분석.
//          role="tablist" 로 만들고 ←→·Home/End 로 옮긴다. 묶음 전체가 탭 정지 하나다
//          (roving tabindex) — 탭이 다섯 개라고 Tab 을 다섯 번 누르게 하지 않는다.
//
// tabs 에서 **화살표는 포커스만 옮기고 고르지는 않는다**(수동 활성화). 탭 하나를 열 때마다
// DART·SEC 를 부르기 때문이다. 화살표로 훑기만 해도 요청이 나가면 남의 서버를 두드리게
// 된다. 고르는 것은 Enter 나 Space 로 한다. 마우스는 지금까지처럼 누르면 바로 열린다.

type Option<T extends string> = {
  value: T
  label: string
  /** 마우스를 올렸을 때의 설명. "3개월: 그 분기만 / 누적: 연초부터" 같은 것. */
  title?: string
}

type SegmentedProps<T extends string> = {
  options: readonly Option<T>[]
  value: T
  onChange: (next: T) => void
  /** 스크린리더가 읽을 묶음 이름. "정렬 기준", "재무 기간" 처럼. */
  label: string
  /** sm = 카드 머리글 안의 작은 칩 · md = 화면 상단 도구줄의 알약 */
  size?: 'sm' | 'md'
  /** 테두리로 둘러 한 덩어리로 보이게 한다. 연간↔분기처럼 짧은 쌍에 쓴다. */
  grouped?: boolean
  /** 묶음 전체에 붙는 설명. */
  title?: string
  /** group = 필터·토글(기본) · tabs = 화면을 갈아 끼우는 탭. 위 주석 참고. */
  kind?: 'group' | 'tabs'
  /**
   * tabs 일 때 탭과 패널을 잇는 id 앞머리. 이것을 주면 각 버튼이
   * `{prefix}-tab-{값}` id 를 갖고 `{prefix}-panel-{값}` 을 가리킨다.
   * 화면 쪽에서 그 id 로 패널을 그려 줘야 짝이 맞는다.
   */
  idPrefix?: string
  className?: string
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  size = 'sm',
  grouped = false,
  title,
  kind = 'group',
  idPrefix,
  className = '',
}: SegmentedProps<T>) {
  const listRef = useRef<HTMLDivElement>(null)
  const tabs = kind === 'tabs'

  const wrapper = grouped
    ? `flex overflow-hidden rounded border border-neutral-800 ${className}`
    : `flex gap-1 ${className}`

  // 옮긴 곳에 진짜 포커스를 준다. 포커스가 따라가지 않으면 스크린리더가 어디로 갔는지
  // 말해 주지 못한다. 끝에서 한 칸 더 가면 반대쪽 끝으로 돈다 — 탭 묶음의 관례다.
  const moveFocus = (from: number, delta: number | 'first' | 'last') => {
    const next =
      delta === 'first'
        ? 0
        : delta === 'last'
          ? options.length - 1
          : (from + delta + options.length) % options.length
    const target = listRef.current?.children[next] as HTMLElement | undefined
    target?.focus()
  }

  const handleKey = (event: React.KeyboardEvent, index: number) => {
    switch (event.key) {
      case 'ArrowRight':
        event.preventDefault()
        moveFocus(index, 1)
        break
      case 'ArrowLeft':
        event.preventDefault()
        moveFocus(index, -1)
        break
      case 'Home':
        event.preventDefault()
        moveFocus(index, 'first')
        break
      case 'End':
        event.preventDefault()
        moveFocus(index, 'last')
        break
    }
  }

  // 고른 것이 탭 정지를 갖는다. 묶음에 들어오는 문은 항상 하나다.
  const focusIndex = Math.max(
    options.findIndex((option) => option.value === value),
    0,
  )

  return (
    <div
      ref={listRef}
      role={tabs ? 'tablist' : 'group'}
      aria-label={label}
      title={title}
      className={wrapper}
    >
      {options.map((option, index) => {
        const selected = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role={tabs ? 'tab' : undefined}
            id={tabs && idPrefix ? `${idPrefix}-tab-${option.value}` : undefined}
            aria-controls={tabs && idPrefix ? `${idPrefix}-panel-${option.value}` : undefined}
            aria-selected={tabs ? selected : undefined}
            aria-pressed={tabs ? undefined : selected}
            tabIndex={tabs ? (index === focusIndex ? 0 : -1) : undefined}
            onKeyDown={tabs ? (event) => handleKey(event, index) : undefined}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={`transition-colors ${sizeClass(size, grouped)} ${stateClass(
              selected,
              size,
              grouped,
            )}`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

function sizeClass(size: 'sm' | 'md', grouped: boolean): string {
  if (grouped) return 'px-1.5 py-0.5 text-xs'
  return size === 'md' ? 'rounded-md px-2.5 py-1.5 text-sm' : 'rounded px-2 py-0.5 text-xs'
}

function stateClass(selected: boolean, size: 'sm' | 'md', grouped: boolean): string {
  if (grouped) {
    return selected
      ? 'bg-neutral-700 text-neutral-100'
      : 'text-neutral-400 hover:bg-neutral-800'
  }
  if (selected) return 'bg-neutral-100 text-neutral-900'
  // 도구줄의 알약은 눌리지 않은 것도 바탕이 있어야 버튼으로 보인다.
  return size === 'md'
    ? 'bg-neutral-900 text-neutral-300 hover:bg-neutral-800'
    : 'text-neutral-400 hover:bg-neutral-800'
}
