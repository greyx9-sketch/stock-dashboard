// 라벨-값 한 쌍. 국내·미국 밸류에이션 카드에 글자 단위로 똑같은 것이 두 벌 있었다.
//
// 값이 없을 때 "—" 를 찍지 않고 **못 낸 이유를 그대로 적는 것**이 이 프로젝트의 방식이다.
// PER 이 없는 것은 적자라서일 수도, 자료를 못 받아서일 수도, 우선주라 계산이 안 되는
// 것일 수도 있는데 "—" 하나로는 셋을 구별할 수 없다. 그 규칙을 여기에 담아 둔다.

export function Metric({
  label,
  value,
  suffix,
  sub,
  note,
}: {
  label: string
  value: string | null
  suffix: string
  /** 값 아래 한 줄 더. 근거가 되는 원자료를 적는다. */
  sub?: string
  /** 값이 없을 때 대신 적을 이유. */
  note: string | null
}) {
  return (
    <div>
      <dt className="text-xs text-neutral-500">{label}</dt>
      {value !== null ? (
        <>
          <dd className="tabular text-sm text-neutral-100">
            {value}
            <span className="ml-0.5 text-xs text-neutral-500">{suffix}</span>
          </dd>
          {sub && <dd className="tabular text-xs text-neutral-600">{sub}</dd>}
        </>
      ) : (
        <dd className="text-xs leading-tight text-neutral-500">{note ?? '—'}</dd>
      )}
    </div>
  )
}
