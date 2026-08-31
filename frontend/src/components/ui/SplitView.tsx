import type { ReactNode } from 'react'

// 목록과 상세를 나란히 놓는 틀. 국내·미국·관심·분석 네 화면이 같은 모양을 쓴다.
//
// **좁은 화면에서는 나란히 놓을 수 없다.** 지금까지는 `lg:` 그리드가 풀리면서 상세가
// 목록 **아래로** 내려갔는데, 목록이 50줄이라 휴대폰에서는 종목을 누르고 나서 손가락으로
// 한참 내려야 상세가 나왔다. 누른 것이 열렸는지조차 알 수 없다.
//
// 그래서 좁은 화면에서는 **둘 중 하나만 보여준다** — 목록에서 종목을 누르면 상세로 넘어가고,
// 위의 되돌아가기를 누르면 목록으로 돌아온다. 휴대폰 앱이 대개 이렇게 움직인다.
// `lg` 이상에서는 지금까지처럼 둘이 같이 있고, 되돌아가기 줄은 사라진다.
//
// 무엇을 보고 있는지(`view`)는 화면 쪽이 들고 있다. 목록이 처음 뜰 때 첫 종목을 자동으로
// 여는 화면들이 있는데, 그것까지 "눌렀다"로 치면 휴대폰에서 앱을 열자마자 상세로
// 튕긴다. 자동 선택과 사용자가 누른 것을 구분할 수 있는 쪽은 화면이다.

type Props = {
  /** 좁은 화면에서 지금 보고 있는 것. `lg` 이상에서는 쓰이지 않는다. */
  view: 'list' | 'detail'
  onBack: () => void
  /** 되돌아가기 줄에 적을 말. "종목 목록으로" 처럼. */
  backLabel: string
  /** 그리드 정의. `gap-6 lg:grid-cols-[minmax(0,1fr)_480px]` 처럼 통째로 넘긴다. */
  className: string
  list: ReactNode
  detail: ReactNode
}

export function SplitView({ view, onBack, backLabel, className, list, detail }: Props) {
  const showingDetail = view === 'detail'

  return (
    <div className={`grid ${className}`}>
      {/* `min-w-0` 이 없으면 격자 칸이 **안의 내용만큼 넓어진다**(grid 기본값이
          `min-width: auto` 다). 표 하나가 424px 이면 칸도 424px 이 되고, 그러면 휴대폰
          화면 전체가 가로로 밀린다 — 표 안에서만 밀려야 하는데. */}
      <div className={`min-w-0 ${showingDetail ? 'hidden lg:block' : ''}`}>{list}</div>

      {/* 상세를 화면에 붙잡아 둔다(`lg` 이상). 목록을 끝까지 훑어도 상세는 그 자리에 있고,
          상세가 화면보다 길면 기둥 안에서만 스크롤한다. */}
      <aside
        className={`min-w-0 ${
          showingDetail ? '' : 'hidden lg:block'
        } lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:self-start lg:overflow-y-auto lg:pr-1`}
      >
        {showingDetail && (
          <button
            onClick={onBack}
            className="mb-3 flex w-full items-center gap-1.5 rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-300 transition-colors hover:bg-neutral-800 lg:hidden"
          >
            <span aria-hidden>←</span>
            {backLabel}
          </button>
        )}
        {detail}
      </aside>
    </div>
  )
}
