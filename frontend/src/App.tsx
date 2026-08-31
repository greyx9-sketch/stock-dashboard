import { KrMarket } from './pages/KrMarket'
import { UsMarket } from './pages/UsMarket'
import { Watchlist } from './pages/Watchlist'
import { Calendar } from './pages/Calendar'
import { Screener } from './pages/Screener'
import { MacroStrip } from './components/MacroStrip'
import { UpcomingEvents } from './components/UpcomingEvents'
import { SystemBanner } from './components/SystemBanner'
import { useRoute, type Tab } from './lib/useRoute'

// 화면 전체의 껍데기. 어느 화면을 보고 있는지는 **주소가 들고 있다**(`lib/useRoute`).
// 여기서는 그 주소를 읽어 화면을 고르기만 한다.
//
// 국내와 미국을 한 페이지에 조건문으로 섞지 않은 이유: 목록의 출처(KRX DB vs 토스 랭킹),
// 기준가를 구하는 방식, 재무의 회계 기준이 전부 다르다. 한 컴포넌트에 넣으면 어느 분기가
// 어느 시장을 위한 것인지 금세 알 수 없게 된다.

// 관심종목은 두 시장을 섞어 담으므로 국내·미국과 나란히 놓인 세 번째 탭이다.
// 일정은 시장을 가리지 않는 것(금통위·FOMC·만기)이 대부분이라 맨 뒤에 둔다.
const TABS: { key: Tab; label: string }[] = [
  { key: 'kr', label: '국내' },
  { key: 'us', label: '미국' },
  { key: 'watch', label: '관심' },
  { key: 'screen', label: '분석' },
  { key: 'calendar', label: '일정' },
]

export default function App() {
  const { route, setTab, setSymbol, setSection } = useRoute()
  const { tab, symbol, section } = route

  // 종목을 들고 다니는 세 화면은 같은 것을 받는다. 어느 화면에서 열든 주소가 같은 모양이 된다.
  const detail = { symbol, section, onSelect: setSymbol, onSection: setSection }

  return (
    <>
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
      <div className="mx-auto max-w-7xl px-4 py-6 xl:max-w-[1440px]">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">주식 시세</h1>
        <div className="flex gap-1 rounded-md bg-neutral-900 p-0.5">
          {TABS.map((item) => (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              className={`rounded px-3 py-1 text-sm transition-colors ${
                tab === item.key
                  ? 'bg-neutral-100 text-neutral-900'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {/* key 를 주어 탭을 바꿀 때 이전 화면의 상태가 남지 않게 한다. */}
      {tab === 'kr' && <KrMarket key="kr" {...detail} />}
      {tab === 'us' && <UsMarket key="us" {...detail} />}
      {tab === 'watch' && <Watchlist key="watch" {...detail} />}
      {tab === 'screen' && <Screener key="screen" />}
      {tab === 'calendar' && <Calendar key="calendar" />}
      </div>
    </>
  )
}
