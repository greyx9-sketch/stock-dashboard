// 숫자를 사람이 읽는 형태로 바꾸는 함수들.
//
// 계산은 하지 않는다. 서버가 계산한 값을 표기만 바꾼다.

const won = new Intl.NumberFormat('ko-KR')

/** 원 단위 정수에 천단위 콤마. */
export function formatWon(value: number): string {
  return won.format(value)
}

/** 조·억 단위로 줄여 쓴다. 시가총액·거래대금처럼 자릿수가 큰 값에 쓴다. */
export function formatBigWon(value: number): string {
  const jo = 1_0000_0000_0000
  const eok = 1_0000_0000
  if (Math.abs(value) >= jo) return `${(value / jo).toFixed(1)}조`
  if (Math.abs(value) >= eok) return `${Math.round(value / eok).toLocaleString('ko-KR')}억`
  return won.format(value)
}

/** 거래량은 주 단위라 만/천 단위로 줄인다. */
export function formatVolume(value: number): string {
  if (value >= 1_0000_0000) return `${(value / 1_0000_0000).toFixed(1)}억`
  if (value >= 1_0000) return `${Math.round(value / 1_0000).toLocaleString('ko-KR')}만`
  return won.format(value)
}

/** 부호를 항상 붙인 등락률. 0 은 부호 없이 둔다. */
export function formatRate(rate: string | number): string {
  const value = typeof rate === 'string' ? Number(rate) : rate
  if (!Number.isFinite(value)) return '-'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

/**
 * 부호를 붙이지 않는 비율. 마진·ROE·부채비율처럼 **변화가 아니라 수준**을 나타내는 값에 쓴다.
 * 부채비율 "+29.94%" 는 늘었다는 뜻으로 잘못 읽힌다. 음수면 마이너스는 그대로 남긴다.
 */
export function formatPercent(rate: string | number): string {
  const value = typeof rate === 'string' ? Number(rate) : rate
  if (!Number.isFinite(value)) return '-'
  return `${value.toFixed(2)}%`
}

/** 부호를 항상 붙인 금액 변화. */
export function formatChange(change: string | number): string {
  const value = typeof change === 'string' ? Number(change) : change
  if (!Number.isFinite(value)) return '-'
  const sign = value > 0 ? '+' : ''
  return `${sign}${won.format(value)}`
}

/**
 * 등락에 따른 글자색. 국내 관례대로 상승 빨강 / 하락 파랑이다.
 * 보합(0)은 회색으로 둬서 "변화 없음"이 눈에 띄지 않게 한다.
 */
export function changeColor(value: string | number): string {
  const num = typeof value === 'string' ? Number(value) : value
  if (!Number.isFinite(num) || num === 0) return 'text-neutral-400'
  return num > 0 ? 'text-up' : 'text-down'
}

/** 2026-08-07 → 8/7 (금) */
export function formatShortDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00+09:00`)
  const weekday = ['일', '월', '화', '수', '목', '금', '토'][date.getDay()]
  return `${date.getMonth() + 1}/${date.getDate()} (${weekday})`
}

/** ISO 시각 → 8/10 19:59 */
export function formatTimestamp(iso: string | null): string {
  if (!iso) return '-'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getMonth() + 1}/${date.getDate()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
