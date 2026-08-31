// 일정의 종류와 그 색. 달력 격자·목록·범례·추가 폼이 전부 같은 것을 봐야 해서
// 한 곳에 모은다. 예전에는 `Calendar.tsx` 안에 있었고 그 파일이 425 줄이었다.

export const KIND_STYLE: Record<string, { dot: string; text: string }> = {
  금통위: { dot: 'bg-amber-400', text: 'text-amber-300' },
  FOMC: { dot: 'bg-sky-400', text: 'text-sky-300' },
  만기: { dot: 'bg-violet-400', text: 'text-violet-300' },
  실적: { dot: 'bg-emerald-400', text: 'text-emerald-300' },
  배당: { dot: 'bg-rose-400', text: 'text-rose-300' },
  공모주: { dot: 'bg-orange-400', text: 'text-orange-300' },
  기타: { dot: 'bg-neutral-400', text: 'text-neutral-300' },
}

/** 사용자가 직접 만들 수 있는 종류. 금통위·FOMC·만기는 자동으로만 들어온다. */
export const CREATABLE = ['실적', '배당', '공모주', '기타']

export const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

export function style(kind: string) {
  return KIND_STYLE[kind] ?? KIND_STYLE.기타
}

/** `2026-08-24` → 24. 시간대 때문에 Date 로 바꾸지 않고 문자열에서 바로 뗀다. */
export function dayOf(iso: string): number {
  return Number(iso.slice(8, 10))
}

/** `2026`, `8`, `24` → `2026-08-24` */
export function isoOf(year: number, month: number, day: number): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${year}-${pad(month)}-${pad(day)}`
}

export function todayIso(): string {
  const now = new Date()
  return isoOf(now.getFullYear(), now.getMonth() + 1, now.getDate())
}
