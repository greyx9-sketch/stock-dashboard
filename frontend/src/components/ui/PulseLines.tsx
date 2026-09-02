import type { CSSProperties } from 'react'

/* 화면 뒤에 깔리는 세로선 격자와, 그 선을 타고 아래로 흐르는 옅은 맥박.
   Originkit 의 pulse-lines 가 공개한 규격(shape·type·lineColor·lineWidth·gap·
   scale·speed)을 우리 규격으로 구현한 것이다. 코드가 아니라 방식을 가져왔다.

   원본은 캔버스에 매 프레임 그린다. 여기서는 그리지 않는다 —
   격자와 맥박 둘 다 repeating-linear-gradient 한 장이고, 움직이는 것은
   transform 하나뿐이다. 이 화면은 이미 웹소켓과 1초 폴링을 돌리고 있어서
   매 프레임 자바스크립트가 도는 층을 뒤에 하나 더 깔고 싶지 않았다.
   그래서 원본이 데스크톱용인 것과 달리 휴대폰에서도 켜 둔다.

   ── 색을 쓰지 않는 이유 ────────────────────────────────────────────
   원본은 최대 5색 팔레트를 훑고 지나간다. 이 화면에서는 안 된다.
   초록·빨강은 등락, 파랑은 하락이라는 뜻을 이미 갖고 있어서(같은 이유로
   포커스 링도 무채색이다) 배경이 그 색으로 흐르면 숫자 옆에서 방향으로
   오독된다. 흰색을 아주 옅게만 쓴다.

   ── 위쪽을 지우는 이유 ────────────────────────────────────────────
   화면 맨 위는 매크로 띠와 일정 띠가 빽빽하다. 거기까지 격자가 올라오면 글자
   뒤가 지저분해진다. 그 아래부터 서서히 드러나게 한다.

   비율(%)이 아니라 픽셀로 끊는다. 가리려는 것이 화면 높이에 비례하는 것이
   아니라 높이가 정해진 띠 두 개이기 때문이다. 비율로 두면 세로로 긴 화면에서는
   멀쩡한 영역까지 지워지고, 짧은 화면에서는 띠를 다 못 가린다. */

type Props = {
  /** 선 사이 간격(px). */
  gap?: number
  /** 선 두께(px). */
  lineWidth?: number
  /** 맥박이 지나가지 않는 동안의 선 색. */
  lineColor?: string
  /** 흘러가는 빛의 색. */
  pulseColor?: string
  /** 빛나는 구간의 길이(px). */
  dash?: number
  /** 맥박이 다시 나타나기까지의 거리(px). 이 값만큼 내려보내면 이음매가 없다. */
  period?: number
  /** 한 주기를 도는 데 걸리는 시간(초). */
  seconds?: number
}

export function PulseLines({
  gap = 44,
  lineWidth = 1,
  lineColor = 'rgba(255, 255, 255, 0.03)',
  pulseColor = 'rgba(255, 255, 255, 0.18)',
  dash = 96,
  period = 560,
  seconds = 16,
}: Props) {
  // 세로선 한 벌. 격자로도 쓰고, 맥박을 이 모양으로 잘라 내는 마스크로도 쓴다.
  const columns = `repeating-linear-gradient(90deg, #000 0 ${lineWidth}px, transparent ${lineWidth}px ${gap}px)`

  const mask: CSSProperties = {
    maskImage: columns,
    WebkitMaskImage: columns,
  }

  return (
    <div
      aria-hidden
      style={{
        position: 'fixed',
        inset: 0,
        // #root 에 쌓임 맥락이 없으므로 본문 아래·body 배경 위에 정확히 놓인다.
        zIndex: -1,
        pointerEvents: 'none',
        overflow: 'hidden',
        // 위쪽의 빽빽한 띠들을 피해 아래로 갈수록 드러난다.
        maskImage: 'linear-gradient(180deg, transparent 0 64px, rgba(0,0,0,0.5) 150px, #000 280px)',
        WebkitMaskImage:
          'linear-gradient(180deg, transparent 0 64px, rgba(0,0,0,0.5) 150px, #000 280px)',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `repeating-linear-gradient(90deg, ${lineColor} 0 ${lineWidth}px, transparent ${lineWidth}px ${gap}px)`,
        }}
      />

      <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', ...mask }}>
        <div
          className="ok-pulse-run"
          style={
            {
              position: 'absolute',
              left: 0,
              right: 0,
              // 한 주기만큼 위에서 시작해 한 주기만큼 내려간다. 그동안 위쪽이
              // 비지 않도록 그만큼 더 길게 잡는다.
              top: -period,
              height: `calc(100% + ${period}px)`,
              animationDuration: `${seconds}s`,
              '--ok-pulse-period': `${period}px`,
              // 한 주기 안에서 어둠 → 빛 → 어둠. 마지막 정지점이 반복 주기가 된다.
              background: `repeating-linear-gradient(180deg, transparent 0px, transparent ${period - dash}px, ${pulseColor} ${period - dash / 2}px, transparent ${period}px)`,
            } as CSSProperties
          }
        />
      </div>
    </div>
  )
}
