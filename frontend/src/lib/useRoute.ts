import { useCallback, useEffect, useRef, useState } from 'react'

// 주소(URL)와 화면을 잇는다. 라이브러리를 쓰지 않고 여기서 끝낸다.
//
// 이 앱의 길찾기는 축이 세 개뿐이다 — 어느 탭 · 어느 종목 · 종목의 어느 섹션.
// 중첩 화면도 경로 매개변수도 없어서 라우터 라이브러리가 다루는 개념이 남아돈다.
//
//   #/kr                  국내 탭
//   #/kr/005930           삼성전자 상세 (개요)
//   #/kr/005930/finance   삼성전자 · 재무
//   #/us/AAPL/filings     애플 · 공시·분석
//   #/watch #/screen #/calendar
//
// **해시(#)를 쓰는 이유**: 해시 뒤는 서버로 가지 않는다. 그래서 배포 서버(Caddy)에
// "어떤 주소로 들어와도 index.html 을 주라"는 설정을 따로 넣지 않아도 새로고침이 된다.
// 설정 파일을 건드리지 않는 만큼 배포에서 깨질 구석이 하나 줄어든다.

export const TABS = ['kr', 'us', 'watch', 'screen', 'calendar'] as const
export type Tab = (typeof TABS)[number]

export const SECTIONS = ['overview', 'finance', 'filings'] as const
export type Section = (typeof SECTIONS)[number]

/** 상세 섹션 전환 버튼에 그대로 넘긴다. 국내·미국이 같은 것을 써야 구조가 어긋나지 않는다. */
export const SECTION_OPTIONS = [
  { value: 'overview', label: '개요' },
  { value: 'finance', label: '재무' },
  { value: 'filings', label: '공시·분석' },
] as const satisfies readonly { value: Section; label: string }[]

export type Route = {
  tab: Tab
  symbol: string | null
  section: Section
}

const DEFAULT_ROUTE: Route = { tab: 'kr', symbol: null, section: 'overview' }

// 국내는 6자리 숫자, 미국은 알파벳 티커(BRK.B 처럼 점이 섞이기도 한다).
// 주소창에 아무 글자나 쳐 넣어도 화면이 이상해지지 않게 여기서 한 번 거른다.
const SYMBOL_PATTERN = /^[A-Za-z0-9.-]{1,12}$/

export function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)

  const tab = (TABS as readonly string[]).includes(parts[0]) ? (parts[0] as Tab) : DEFAULT_ROUTE.tab
  const raw = parts[1] ?? ''
  const symbol = SYMBOL_PATTERN.test(raw) ? raw.toUpperCase() : null
  const section = (SECTIONS as readonly string[]).includes(parts[2])
    ? (parts[2] as Section)
    : DEFAULT_ROUTE.section

  return { tab, symbol, section }
}

export function formatHash(route: Route): string {
  const parts: string[] = [route.tab]
  if (route.symbol) {
    parts.push(route.symbol)
    // 개요는 기본값이라 주소에 적지 않는다. #/kr/005930 이 #/kr/005930/overview 보다 읽기 좋다.
    if (route.section !== 'overview') parts.push(route.section)
  }
  return `#/${parts.join('/')}`
}

export function useRoute() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))

  // 최신 route 를 setter 안에서 읽어야 하는데, 매번 새 setter 를 만들면 그것을 받는
  // 화면들이 통째로 다시 그려진다. ref 로 값만 따로 들고 setter 는 고정한다.
  const latest = useRef(route)
  latest.current = route

  useEffect(() => {
    // 뒤로/앞으로 가기는 popstate 로, 주소창 직접 수정은 hashchange 로 온다.
    // 둘 다 같은 일을 하므로 같은 처리에 묶는다.
    const sync = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('popstate', sync)
    window.addEventListener('hashchange', sync)
    return () => {
      window.removeEventListener('popstate', sync)
      window.removeEventListener('hashchange', sync)
    }
  }, [])

  // 주소를 바꾸는 방법이 둘이다.
  //   push    뒤로가기로 돌아올 지점을 남긴다. 탭·섹션 전환이 여기다.
  //   replace 지점을 남기지 않는다. 종목 선택이 여기다 — 표에서 ↑↓ 로 훑으면 한 칸
  //           옮길 때마다 종목이 바뀌는데, 그때마다 지점을 남기면 뒤로가기를 수십 번
  //           눌러야 빠져나가는 상태가 된다.
  const go = useCallback((next: Route, mode: 'push' | 'replace') => {
    const hash = formatHash(next)
    if (hash !== window.location.hash) {
      const url = `${window.location.pathname}${window.location.search}${hash}`
      if (mode === 'push') window.history.pushState(null, '', url)
      else window.history.replaceState(null, '', url)
    }
    // pushState·replaceState 는 hashchange 를 일으키지 않는다. 상태는 직접 맞춰야 한다.
    setRoute(next)
  }, [])

  // 탭을 옮기면 종목을 놓는다. 국내 종목 코드를 들고 미국 탭으로 건너가면 안 되기 때문이다.
  const setTab = useCallback(
    (tab: Tab) => go({ tab, symbol: null, section: 'overview' }, 'push'),
    [go],
  )

  // 섹션은 유지한다. 재무를 보다가 다른 종목을 누르면 그 종목의 재무가 나오는 것이
  // 비교하는 흐름에 맞는다.
  const setSymbol = useCallback(
    (symbol: string | null) => go({ ...latest.current, symbol }, 'replace'),
    [go],
  )

  const setSection = useCallback(
    (section: Section) => go({ ...latest.current, section }, 'push'),
    [go],
  )

  return { route, setTab, setSymbol, setSection }
}
