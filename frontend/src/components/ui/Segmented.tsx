// 서로 배타적인 선택지를 나란히 놓는 버튼 묶음. 화면 다섯 곳에 각각 하드코딩되어 있었다.
//   · 국내 목록의 정렬(시가총액/거래대금/거래량/등락률)과 시장(전체/KOSPI/KOSDAQ)
//   · 재무 카드의 지표(매출/영업이익/순이익)
//   · 공시 카드의 유형 필터 5 개
//   · 재무의 연간↔분기, 3개월↔누적
//
// 접근성이 여기서 한 번에 해결된다. 지금까지는 그냥 <button> 나열이라 스크린리더가
// "이 중 하나를 고르는 것"임을 알 수 없었다. role="group" 과 aria-pressed 를 붙인다.

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
  className = '',
}: SegmentedProps<T>) {
  const wrapper = grouped
    ? `flex overflow-hidden rounded border border-neutral-800 ${className}`
    : `flex gap-1 ${className}`

  return (
    <div role="group" aria-label={label} title={title} className={wrapper}>
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
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
