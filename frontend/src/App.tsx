import { useState } from 'react'
import { KrMarket } from './pages/KrMarket'
import { UsMarket } from './pages/UsMarket'
import { Watchlist } from './pages/Watchlist'
import { MacroStrip } from './components/MacroStrip'
import { SystemBanner } from './components/SystemBanner'

// 화면 전체의 껍데기. 어느 시장을 보고 있는지만 들고 있고, 나머지는 각 페이지가 맡는다.
//
// 국내와 미국을 한 페이지에 조건문으로 섞지 않은 이유: 목록의 출처(KRX DB vs 토스 랭킹),
// 기준가를 구하는 방식, 재무의 회계 기준이 전부 다르다. 한 컴포넌트에 넣으면 어느 분기가
// 어느 시장을 위한 것인지 금세 알 수 없게 된다.

// 관심종목은 두 시장을 섞어 담으므로 국내·미국과 나란히 놓인 세 번째 탭이다.
type Tab = 'KR' | 'US' | 'WATCH'

const TABS: { key: Tab; label: string }[] = [
  { key: 'KR', label: '국내' },
  { key: 'US', label: '미국' },
  { key: 'WATCH', label: '관심' },
]

export default function App() {
  const [country, setCountry] = useState<Tab>('KR')

  return (
    <>
      {/* 고장 알림은 맨 위에 둔다. 숫자가 이상해 보일 때 원인을 먼저 보게 하려는 것이다. */}
      <SystemBanner />

      {/* 매크로 띠는 시장 탭 바깥에 둔다. 탭을 바꿔도 다시 받지 않게 하려는 것이다. */}
      <MacroStrip />

      <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">주식 시세</h1>
        <div className="flex gap-1 rounded-md bg-neutral-900 p-0.5">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setCountry(tab.key)}
              className={`rounded px-3 py-1 text-sm transition-colors ${
                country === tab.key
                  ? 'bg-neutral-100 text-neutral-900'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* key 를 주어 탭을 바꿀 때 이전 화면의 상태가 남지 않게 한다. */}
      {country === 'KR' && <KrMarket key="KR" />}
      {country === 'US' && <UsMarket key="US" />}
      {country === 'WATCH' && <Watchlist key="WATCH" />}
      </div>
    </>
  )
}
