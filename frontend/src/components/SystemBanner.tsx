import { useEffect, useState } from 'react'
import { fetchHealth } from '../lib/api'
import type { HealthDetail } from '../lib/api'

// 앱이 고장났을 때 화면 맨 위에 알리는 띠.
//
// 서버의 감시 스크립트가 웹훅으로 보내는 것과 **같은 판단**을 읽는다. 사이트를 열어 본
// 사람은 여기서 바로 알고, 안 보고 있을 때는 알림이 간다.
//
// 정상일 때는 아무것도 그리지 않는다. 늘 떠 있는 "정상입니다" 띠는 며칠 만에 눈에서
// 사라져서, 진짜 경고가 떴을 때도 못 알아보게 된다.

const POLL_MS = 60_000

const STYLE: Record<string, string> = {
  down: 'border-red-900/60 bg-red-950/50 text-red-200',
  degraded: 'border-amber-900/60 bg-amber-950/40 text-amber-200',
}

export function SystemBanner() {
  const [health, setHealth] = useState<HealthDetail | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      fetchHealth()
        .then((result) => !cancelled && setHealth(result))
        .catch(() => {
          // 상태를 못 받는 것 자체는 띠로 알리지 않는다. 서버가 아예 죽었다면 화면의
          // 다른 부분이 먼저 오류를 보여주고, 알림은 감시 스크립트가 보낸다.
        })
    }
    load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  if (!health || health.status === 'ok') return null
  // 같은 내용을 닫았으면 다시 띄우지 않는다. 내용이 바뀌면 새 문제이므로 다시 띄운다.
  if (dismissed === health.summary) return null

  const problems = health.checks.filter((c) => c.status !== 'ok')

  return (
    <div className={`border-b px-4 py-2 text-sm ${STYLE[health.status] ?? STYLE.degraded}`}>
      <div className="mx-auto flex max-w-7xl items-start gap-3">
        <span className="font-medium">
          {health.status === 'down' ? '일부 기능이 멈췄습니다' : '일부 기능이 불안정합니다'}
        </span>
        <ul className="min-w-0 flex-1">
          {problems.map((check) => (
            <li key={check.name} className="truncate">
              <span className="opacity-70">{check.name}</span> — {check.detail}
            </li>
          ))}
        </ul>
        <button
          onClick={() => setDismissed(health.summary)}
          className="shrink-0 rounded px-1.5 text-xs opacity-60 transition-opacity hover:opacity-100"
          title="닫기"
        >
          ✕
        </button>
      </div>
    </div>
  )
}
