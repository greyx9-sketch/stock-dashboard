import type { ReactNode } from 'react'

/* 마인드맵 — 이 회사의 구조를 한 장으로.
 *
 * ── 무엇을 위한 그림인가 ──────────────────────────────────────────────
 * 아래 구획들이 이미 같은 내용을 더 자세히 담고 있다. 이 그림은 **먼저 읽는 지도**다 —
 * 이 회사에 대해 우리가 무엇무엇을 아는지, 그 덩어리가 몇 개인지를 스크롤 전에 보여준다.
 * 그래서 가지에는 **이름만** 놓고 설명은 놓지 않는다. 설명까지 넣으면 아래 구획을
 * 한 번 더 쓴 것이 되어, 지도가 아니라 중복이 된다.
 *
 * ── 방사형이 아니라 가로 나무인 이유 ──────────────────────────────────
 * 가운데에서 사방으로 뻗는 모양이 마인드맵의 전형이지만, 그러려면 각 노드의 **크기를
 * 알아야** 자리를 정할 수 있다. 글자 수가 회사마다 다르고 한글·영문이 섞이므로 크기를
 * 미리 알 방법이 없다 — 브라우저가 그린 뒤에 재서 다시 배치하는 수밖에 없고, 그건
 * 화면이 한 번 덜컹거린다는 뜻이다.
 *
 * 가로 나무는 그 문제가 없다. 왼쪽에 줄기, 오른쪽에 가지를 쌓으면 높이는 내용이 알아서
 * 정하고, 좁은 화면에서는 세로로 접힌다. 잇는 선은 SVG 가 아니라 **테두리**로 긋는다 —
 * 좌표가 필요 없고 글자가 접혀도 선이 따라 늘어난다.
 *
 * ── 색을 쓰지 않는다 ──────────────────────────────────────────────────
 * 원본 마인드맵은 가지마다 색을 달리한다. 이 화면에서는 안 된다. 빨강·파랑이 이미
 * 상승·하락이고 호박색은 주의다. 남는 색으로 네 가지를 구분하면 뜻 없는 색이 시세
 * 숫자 옆에서 방향으로 오독된다. 대신 **가지 이름과 개수**로 구분한다.
 */

/* 잎 하나에 허용하는 길이. 넘으면 자르고 전체는 말풍선에 담는다.
 *
 * 실측해 보고 넣었다. 삼성전자의 위험 제목이 "자동차 생산 감소와 전장부품용 반도체
 * 공급 제약이 Harman에 미치는 영향"(38자)이라 지도가 글벽이 됐다. 지도는 **몇 덩어리
 * 인지를 한눈에** 보여주는 그림인데, 잎 하나가 세 줄을 먹으면 그 일을 못 한다.
 *
 * 자르는 것이 아깝지 않은 이유: 같은 내용이 바로 아래 구획에 온전히 다시 나온다.
 * 여기는 목차지 본문이 아니다. */
const LEAF_MAX = 18

function short(text: string): string {
  return text.length > LEAF_MAX ? `${text.slice(0, LEAF_MAX)}…` : text
}

export type MindMapBranch = {
  /** 가지 이름. 예: '사업 부문' */
  label: string
  /** 잎 하나하나. 이름만 놓는다 — 설명은 아래 구획의 몫이다. */
  leaves: string[]
  /** 가지 이름 옆의 한 줄. 이 가지가 무엇인지. */
  note?: string
}

type Props = {
  /** 줄기에 놓을 회사 이름. */
  title: string
  /** 줄기 아래 한 줄. 이 회사가 뭘로 도는지. */
  subtitle?: string | null
  branches: MindMapBranch[]
}

export function MindMap({ title, subtitle, branches }: Props) {
  // 잎이 하나도 없는 가지는 그리지 않는다. 빈 가지는 "그런 게 없다"가 아니라
  // "아직 못 받았다"로 읽힌다.
  const drawn = branches.filter((branch) => branch.leaves.length > 0)
  if (drawn.length === 0) return null

  return (
    <figure className="m-0 overflow-hidden rounded-lg border border-neutral-800 bg-neutral-950/40 p-3">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,13rem)_1fr] lg:items-start">
        {/* 줄기 */}
        <div className="rounded-md border border-neutral-600 bg-surface-raised px-3 py-2.5">
          <div className="text-sm font-medium text-neutral-100">{title}</div>
          {subtitle && (
            <div className="mt-1 text-[11px] leading-relaxed text-neutral-500">{subtitle}</div>
          )}
        </div>

        {/* 가지. 왼쪽 테두리 하나가 줄기에서 뻗은 척추가 된다. */}
        <ul className="space-y-2 lg:border-l lg:border-neutral-800 lg:pl-4">
          {drawn.map((branch) => (
            <Branch key={branch.label} branch={branch} />
          ))}
        </ul>
      </div>
    </figure>
  )
}

function Branch({ branch }: { branch: MindMapBranch }) {
  return (
    <li className="relative">
      {/* 척추에서 이 가지로 뻗는 짧은 가로선. 넓은 화면에서만 보인다. */}
      <span
        aria-hidden
        className="absolute -left-4 top-2.5 hidden h-px w-3 bg-neutral-800 lg:block"
      />
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <Label>{branch.label}</Label>
        {branch.note && <span className="text-[10px] text-neutral-600">{branch.note}</span>}
        <span className="text-[10px] tabular text-neutral-600">{branch.leaves.length}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-1">
        {branch.leaves.map((leaf) => (
          <span
            key={leaf}
            // 자른 것은 말풍선으로 온전히 볼 수 있게 한다. 자른 티를 내지 않으면
            // 사용자는 저게 원문 전체라고 읽는다.
            title={leaf.length > LEAF_MAX ? leaf : undefined}
            className="rounded border border-neutral-800 bg-neutral-950/60 px-1.5 py-0.5 text-[11px] leading-relaxed text-neutral-400"
          >
            {short(leaf)}
          </span>
        ))}
      </div>
    </li>
  )
}

function Label({ children }: { children: ReactNode }) {
  return <span className="text-[11px] font-medium text-neutral-300">{children}</span>
}
