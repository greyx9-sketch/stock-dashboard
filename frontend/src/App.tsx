import { KrMarket } from './pages/KrMarket'
import { UsMarket } from './pages/UsMarket'
import { Watchlist } from './pages/Watchlist'
import { Calendar } from './pages/Calendar'
import { Screener } from './pages/Screener'
import { MacroStrip } from './components/MacroStrip'
import { UpcomingEvents } from './components/UpcomingEvents'
import { SystemBanner } from './components/SystemBanner'
import { Segmented } from './components/ui/Segmented'
import { PulseLines } from './components/ui/PulseLines'
import { useRoute, type Tab } from './lib/useRoute'

// 화면 전체의 껍데기. 어느 화면을 보고 있는지는 **주소가 들고 있다**(`lib/useRoute`).
// 여기서는 그 주소를 읽어 화면을 고르기만 한다.
//
// 국내와 미국을 한 페이지에 조건문으로 섞지 않은 이유: 목록의 출처(KRX DB vs 토스 랭킹),
// 기준가를 구하는 방식, 재무의 회계 기준이 전부 다르다. 한 컴포넌트에 넣으면 어느 분기가
// 어느 시장을 위한 것인지 금세 알 수 없게 된다.

// 관심종목은 두 시장을 섞어 담으므로 국내·미국과 나란히 놓인 세 번째 탭이다.
// 일정은 시장을 가리지 않는 것(금통위·FOMC·만기)이 대부분이라 맨 뒤에 둔다.
const TABS = [
  { value: 'kr', label: '국내' },
  { value: 'us', label: '미국' },
  { value: 'watch', label: '관심' },
  { value: 'screen', label: '분석' },
  { value: 'calendar', label: '일정' },
] as const satisfies readonly { value: Tab; label: string }[]

export default function App() {
  const { route, setTab, setSymbol, setSection } = useRoute()
  const { tab, symbol, section } = route

  // 종목을 들고 다니는 세 화면은 같은 것을 받는다. 어느 화면에서 열든 주소가 같은 모양이 된다.
  const detail = { symbol, section, onSelect: setSymbol, onSection: setSection }

  return (
    <>
      {/* 화면 전체 뒤에 깔리는 층. 본문보다 아래(z-index: -1)에 고정돼 있어
          스크롤해도 따라오지 않고, 클릭도 가로채지 않는다. */}
      <PulseLines />

      {/* 고장 알림은 맨 위에 둔다. 숫자가 이상해 보일 때 원인을 먼저 보게 하려는 것이다. */}
      <SystemBanner />

      {/* 매크로 띠는 시장 탭 바깥에 둔다. 탭을 바꿔도 다시 받지 않게 하려는 것이다. */}
      <MacroStrip />

      {/* 다가오는 일정도 같은 이유로 탭 바깥이다 — 금통위가 이틀 뒤라는 사실은 국내를
          보든 미국을 보든 똑같이 중요하다. 다만 일정 탭에서는 아래에 달력이 통째로
          있으므로 겹쳐 두지 않는다. */}
      {tab !== 'calendar' && <UpcomingEvents />}

      {/* 1280px 은 이만한 표를 담기에 좁다. 큰 화면에서는 목록에 폭을 더 준다.
          — 그래야 시가총액 열까지 가로 스크롤 없이 들어온다. */}
      <div className="mx-auto max-w-7xl px-3 py-4 sm:px-4 sm:py-6 xl:max-w-[1440px]">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold sm:text-2xl">주식 시세</h1>
        {/* 지금까지는 그냥 <button> 다섯 개였다. 스크린리더에는 "화면을 고르는 곳"이라는
            것이 전달되지 않았고, 키보드로는 Tab 을 다섯 번 눌러 지나가야 했다.
            묶음 전체가 탭 정지 하나가 되고 ←→ 로 옮긴다. */}
        <Segmented
          kind="tabs"
          idPrefix="market"
          size="md"
          label="화면"
          options={TABS}
          value={tab}
          onChange={setTab}
          className="rounded-md bg-neutral-900 p-0.5"
        />
      </div>

      {/* key 를 주어 탭을 바꿀 때 이전 화면의 상태가 남지 않게 한다.
          id 는 위 탭이 aria-controls 로 가리키는 짝이다. */}
      <div
        role="tabpanel"
        id={`market-panel-${tab}`}
        aria-labelledby={`market-tab-${tab}`}
        tabIndex={-1}
      >
        {tab === 'kr' && <KrMarket key="kr" {...detail} />}
        {tab === 'us' && <UsMarket key="us" {...detail} />}
        {tab === 'watch' && <Watchlist key="watch" {...detail} />}
        {tab === 'screen' && <Screener key="screen" {...detail} />}
        {tab === 'calendar' && <Calendar key="calendar" />}
      </div>
      </div>
    </>
  )
}
