// 기다리는 동안 자리를 잡아 두는 회색 막대.
//
// 상세 화면은 카드 여러 개가 각자 자기 자료를 받는다. 지금까지는 기다리는 동안
// "불러오는 중…" 한 줄만 있다가 내용이 들어오면서 아래 카드들을 통째로 밀어내
// **종목을 바꿀 때마다 화면이 몇 초간 출렁였다.** 읽으려던 줄이 손 밑에서 도망간다.
//
// 고치는 방법은 로딩을 빠르게 만드는 것이 아니라 **들어올 자리를 미리 비워 두는 것**이다.
// 막대의 개수로 대략의 높이를 맞춰 둔다.
//
// `Loading` 과의 구분: 화면에 이미 값이 있고 그 옆에서 갱신을 기다릴 때는 `Loading`,
// 아직 아무것도 없어 자리부터 잡아야 할 때는 이것.

const WIDTHS = ['92%', '78%', '85%', '64%', '88%', '71%']

export function Skeleton({
  rows = 3,
  label,
  className = '',
}: {
  /** 들어올 내용의 대략적인 줄 수. 카드마다 평소 높이에 맞춘다. */
  rows?: number
  /** 스크린리더에게 무엇을 기다리는지 알린다. "재무를 받는 중" 처럼. */
  label: string
  className?: string
}) {
  return (
    <div className={`space-y-2 ${className}`}>
      {/* 눈에는 막대가, 스크린리더에는 문장이 간다. 막대는 소리로 읽을 것이 없다. */}
      <p className="sr-only" aria-live="polite" aria-busy="true">
        {label}
      </p>
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          aria-hidden
          className="h-3 animate-pulse rounded bg-neutral-800"
          style={{ width: WIDTHS[index % WIDTHS.length] }}
        />
      ))}
    </div>
  )
}
