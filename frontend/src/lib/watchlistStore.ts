import { useSyncExternalStore } from 'react'
import {
  addToWatchlist,
  fetchWatchlist,
  moveInWatchlist,
  removeFromWatchlist,
} from './api'
import type { WatchItem } from './api'

// 관심종목 목록을 화면 여러 곳이 함께 본다 — 관심 탭의 표, 국내 상세의 ★, 미국 상세의 ★.
// 셋이 각자 목록을 받아 두면 한 곳에서 담은 종목이 다른 곳에서는 안 담긴 것으로 보인다.
//
// 그래서 모듈 하나가 목록을 들고 있고 화면들은 그것을 구독한다. 상태를 App 까지 올려
// props 로 내려보내는 방법도 있지만, 국내·미국 페이지를 거쳐 상세 패널까지 내려야 해서
// 관계없는 컴포넌트가 관심종목을 알게 된다.
//
// **브라우저 저장소는 쓰지 않는다**(절대 규칙 6). 진짜 목록은 서버 DB 에 있고 이것은
// 화면이 들고 있는 사본일 뿐이다. 새로고침하면 서버에서 다시 받는다.

// 목록을 다시 받는 주기(ms). 서버의 미국 기준가 캐시 수명(5분)과 맞춰 둔다 —
// 미국 세션이 새로 열리면 기준가가 하루 밀리므로 방치하지 않고 주기적으로 새로 받는다.
const REFRESH_MS = 5 * 60 * 1000

type State = {
  items: WatchItem[]
  /** 담긴 종목 코드. ★ 판정에 쓴다 */
  symbols: Set<string>
  loading: boolean
  error: string | null
  /** 한 번이라도 받아 봤는가. 처음 불러오는 중과 "비어 있음"을 구분한다 */
  loaded: boolean
}

let state: State = {
  items: [],
  symbols: new Set(),
  loading: false,
  error: null,
  loaded: false,
}

const listeners = new Set<() => void>()

function publish(next: Partial<State>): void {
  // 객체를 새로 만든다. useSyncExternalStore 는 참조가 바뀌어야 다시 그린다.
  state = { ...state, ...next }
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  // 화면이 처음 붙을 때 한 번 받아 온다. 이미 받아 뒀으면 다시 받지 않는다.
  if (!state.loaded && !state.loading) void refresh()
  return () => {
    listeners.delete(listener)
  }
}

/** 서버에서 목록을 다시 받는다. */
export async function refresh(): Promise<void> {
  publish({ loading: true })
  try {
    const result = await fetchWatchlist()
    publish({
      items: result.items,
      symbols: new Set(result.items.map((i) => i.symbol)),
      loading: false,
      error: null,
      loaded: true,
    })
  } catch (err) {
    // 목록을 못 받아도 이전 목록은 그대로 둔다. 화면이 갑자기 비는 것보다 낫다.
    publish({ loading: false, error: (err as Error).message, loaded: true })
  }
}

/** 담기/빼기를 한 번에. 이미 담긴 종목이면 뺀다. */
export async function toggle(symbol: string): Promise<void> {
  if (state.symbols.has(symbol)) {
    await removeFromWatchlist(symbol)
  } else {
    await addToWatchlist(symbol)
  }
  await refresh()
}

export async function move(symbol: string, direction: 'up' | 'down'): Promise<void> {
  await moveInWatchlist(symbol, direction)
  await refresh()
}

// 목록을 보고 있는 화면이 하나라도 있으면 주기적으로 새로 받는다.
// 아무도 안 보고 있을 때 도는 타이머는 서버만 두드린다.
setInterval(() => {
  if (listeners.size > 0) void refresh()
}, REFRESH_MS)

function getSnapshot(): State {
  return state
}

export function useWatchlist(): State {
  return useSyncExternalStore(subscribe, getSnapshot)
}

/** 이 종목이 담겨 있는가. ★ 버튼 하나만 필요한 화면에서 쓴다. */
export function useIsWatched(symbol: string): boolean {
  const current = useSyncExternalStore(subscribe, getSnapshot)
  return current.symbols.has(symbol)
}
