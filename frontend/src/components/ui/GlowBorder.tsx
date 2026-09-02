import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'

/* 테두리를 한 바퀴 도는 빛. Originkit 의 glow-border 가 공개한 기법을 우리 규격으로
   구현한 것이다(코드가 아니라 방식을 가져왔다).

   원리 — 프레임보다 큰 사각형에 conic 그라디언트를 칠해 돌리고, 마스크로 테두리
   띠만 남긴다. 마스크는 border-box 에서 content-box 를 빼는 방식이라(GlassButton
   의 링과 같은 수법) 정확히 borderWidth 두께의 고리가 나온다.

   왜 이걸 쓰나 — 장식이 아니라 뜻이 있다. 장이 열려 있어 화면의 숫자가 계속
   움직이는 동안에만 빛이 돈다. 마감하면 overlay 자체를 렌더하지 않으므로
   애니메이션도 DOM 도 남지 않는다. 마감된 숫자를 실시간으로 착각하지 않게
   하는 것이 배지의 원래 목적이고, 점 하나보다 이쪽이 멀리서도 보인다.

   비용 — 도는 것은 CSS transform 하나뿐이라 합성 단계에서 처리된다.
   자바스크립트 루프가 없으므로 웹소켓·폴링이 도는 중에도 프레임을 뺏지 않는다.
   ResizeObserver 만 하나 붙는다.

   원본에 있으나 넣지 않은 것 — 마우스를 올리면 빨라지는 hoverMultiplier.
   배지는 올려 놓을 일이 없는 표시라 얻는 것이 없고, 도는 속도를 부드럽게
   바꾸려면 CSS 애니메이션을 버리고 rAF 루프를 돌려야 한다. */

type Props = {
  /** 꺼져 있으면 빛나는 층을 아예 만들지 않는다. */
  active?: boolean
  /** 혜성 머리. 가장 밝은 점. */
  glowColor?: string
  /** 머리 뒤로 끌리는 꼬리. */
  tailColor?: string
  /** 빛이 지나가지 않은 구간의 테두리. */
  baseColor?: string
  /** 고리 두께(px). */
  borderWidth?: number
  /** 모서리 반지름(px). 기본은 알약. */
  radius?: number
  /** 한 바퀴 도는 데 걸리는 시간(초). */
  seconds?: number
  /** 꼬리가 덮는 각도. 클수록 길게 끌린다. */
  tailDegrees?: number
  className?: string
  children: ReactNode
}

export function GlowBorder({
  active = true,
  glowColor = 'rgba(52, 211, 153, 0.95)',
  tailColor = 'rgba(52, 211, 153, 0.35)',
  baseColor = 'rgba(255, 255, 255, 0.05)',
  borderWidth = 1,
  radius = 9999,
  seconds = 4,
  tailDegrees = 70,
  className,
  children,
}: Props) {
  const hostRef = useRef<HTMLSpanElement>(null)
  // 도는 사각형은 프레임의 대각선보다 커야 어느 각도에서도 네 귀퉁이가 비지 않는다.
  // 24px 은 원본이 쓰는 여유분.
  const [span, setSpan] = useState(0)

  useEffect(() => {
    if (!active) return
    const el = hostRef.current
    if (!el) return

    // getBoundingClientRect 가 아니라 contentRect 로 잰다. 부모가 확대·축소
    // 변형을 걸어 두면 getBoundingClientRect 는 화면상 크기를 돌려주어
    // 실제 레이아웃 크기와 어긋난다.
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect
      if (box) setSpan(Math.hypot(box.width, box.height) + 24)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [active])

  const ring: CSSProperties = {
    position: 'absolute',
    inset: 0,
    boxSizing: 'border-box',
    padding: borderWidth,
    borderRadius: radius,
    overflow: 'hidden',
    // 배지 안의 글자나 링크를 가로채지 않는다.
    pointerEvents: 'none',
    background: baseColor,
    // border-box 에서 content-box 를 빼면 남는 것이 정확히 padding 만큼의 띠다.
    maskImage: 'linear-gradient(#000 0 0), linear-gradient(#000 0 0)',
    maskClip: 'border-box, content-box',
    maskComposite: 'exclude',
    WebkitMaskImage: 'linear-gradient(#000 0 0), linear-gradient(#000 0 0)',
    WebkitMaskClip: 'border-box, content-box',
    WebkitMaskComposite: 'xor',
  } as CSSProperties

  return (
    <span
      ref={hostRef}
      className={className}
      style={{ position: 'relative', display: 'inline-flex', isolation: 'isolate' }}
    >
      {children}
      {active && span > 0 && (
        <span aria-hidden style={ring}>
          <span
            className="ok-glow-comet"
            style={{
              position: 'absolute',
              left: '50%',
              top: '50%',
              width: span,
              height: span,
              animationDuration: `${seconds}s`,
              // 머리(0도)에서 꼬리로 흐려지고 나머지는 비운다. 360도에서 다시
              // 투명으로 돌아오므로 한 바퀴를 이어도 이음매가 보이지 않는다.
              background: `conic-gradient(from 0deg, ${glowColor} 0deg, ${tailColor} ${tailDegrees * 0.35}deg, transparent ${tailDegrees}deg, transparent 360deg)`,
            }}
          />
        </span>
      )}
    </span>
  )
}
