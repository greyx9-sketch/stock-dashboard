"""10-K 서술 분석 결과 저장.

이 프로젝트에서 **유일하게 돈이 나가는 경로**라 표를 따로 뒀다. 한 번 분석한 문서를
두 번 부르지 않는 것이 비용 상한의 핵심이고, 그 판단 근거가 여기 기본키다.

기본키를 (접수번호, 모델, 프롬프트 버전) 세 개로 잡은 이유:

- **접수번호(accession_no)**: 같은 회사의 같은 10-K 는 세상에 하나뿐이다. 티커나
  연도가 아니라 이것을 기준으로 삼아야 중복 호출이 원천적으로 막힌다.
- **모델**: 나중에 상위 모델로 다시 돌려 비교하고 싶을 때 둘 다 남는다.
- **프롬프트 버전**: 프롬프트를 고치면 과거 결과가 자동으로 무효가 되는 것이 아니라,
  새 행으로 쌓인다. 옛 결과를 지우지 않고도 새 기준으로 다시 분석할 수 있다.

수치 필드가 없다는 점도 의도한 것이다(CLAUDE.md 절대 규칙 3). 매출·이익은 XBRL 에서
직접 계산해 `sec_financials` 에 넣는다. 여기에는 LLM 이 쓴 **문장만** 들어간다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

STATUS_OK = "ok"
STATUS_FAILED = "failed"
# 배치로 맡겨 놓고 결과를 기다리는 중(`analysis_batch.py`). 돈은 이미 나간 것으로 친다 —
# 그래야 하루 상한이 제출한 건수를 세고, 같은 문서를 두 번 맡기지 않는다.
STATUS_PENDING = "pending"


class SecAnalysis(Base):
    """10-K 한 건에 대한 서술 분석 결과."""

    __tablename__ = "sec_analyses"

    accession_no: Mapped[str] = mapped_column(String(25), primary_key=True)
    model: Mapped[str] = mapped_column(String(40), primary_key=True)
    prompt_version: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 어느 문서인지
    cik: Mapped[str] = mapped_column(String(10))
    ticker: Mapped[str] = mapped_column(String(12))
    fiscal_year: Mapped[int] = mapped_column(Integer)
    period_end: Mapped[str] = mapped_column(String(10), default="")  # YYYY-MM-DD
    filed_date: Mapped[str] = mapped_column(String(10), default="")
    source_url: Mapped[str] = mapped_column(String(400), default="")

    # 분석 본문. 스키마가 바뀔 수 있어 열로 쪼개지 않고 JSON 문자열 하나로 둔다.
    content_json: Mapped[str] = mapped_column(Text, default="")

    # 어떤 항목을 실제로 넣었는지 ("Item 1,Item 1A,Item 7"). 일부만 들어간 경우를
    # 화면에서 밝히기 위한 것이다 — 없는 것을 있는 척하지 않는다.
    sections: Mapped[str] = mapped_column(String(80), default="")
    # 길이 상한에 걸려 잘린 항목. 같은 이유로 남긴다.
    truncated: Mapped[str] = mapped_column(String(80), default="")

    # 경영진 논의를 어느 10-Q 에서 가져왔는지. 비어 있으면 연차의 Item 7 을 썼다는 뜻이다.
    #
    # 이걸 남기는 이유가 둘이다. 하나는 화면 각주에 "어느 시점 자료인가"를 밝히기 위해서고,
    # 다른 하나는 **새 분기보고서가 나왔는지 판단하기 위해서다** — `_should_rerun` 이 이
    # 값과 지금의 최신 10-Q 를 견줘, 다르면 다시 분석할 때가 됐다고 본다.
    #
    # server_default 를 반드시 준다. 없으면 SQLite 가 기존 표에 컬럼 붙이기를 거절하고
    # schema_sync 는 설계대로 경고만 남기고 넘어간다(2026-09-01 에 이것으로 조회가 전부
    # 500 이 났다. `tests/test_schema_sync.py` 끝 주석 참고).
    quarterly_accession: Mapped[str] = mapped_column(String(25), default="", server_default="")
    quarterly_filed_date: Mapped[str] = mapped_column(String(10), default="", server_default="")

    # 비용 기록. input_tokens 가 0 이면 API 를 부르지 않았다는 뜻이고,
    # 하루 호출 상한을 셀 때 이 값으로 실제 호출만 골라낸다.
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 달러는 소수라 부동소수점으로 두면 합계가 어긋난다. 100만분의 1달러 단위 정수로 넣는다.
    cost_micro_usd: Mapped[int] = mapped_column(Integer, default=0)

    # 배치로 맡겼을 때의 배치 id. 이 값이 있고 status 가 pending 이면 결과를 기다리는
    # 중이다. 끝나면 지우지 않고 남겨 둔다 — 어느 배치에서 나온 결과인지 나중에 추적할 수 있게.
    # `server_default` 가 **꼭 있어야 한다.** 파이썬 쪽 `default=` 는 DDL 에 안 나타나서,
    # 이미 행이 있는 표에 NOT NULL 컬럼을 붙일 때 SQLite 가 "기존 행은 뭘로 채우냐"며
    # 거절한다. 그러면 `schema_sync` 가 경고만 남기고 넘어가고, 그 뒤 이 표를 읽는
    # 모든 조회가 `no such column` 500 이 된다 — 실제로 한 번 그렇게 배포했다.
    batch_id: Mapped[str] = mapped_column(String(64), default="", server_default="")

    # 실패도 남긴다. 남기지 않으면 화면을 열 때마다 같은 실패를 다시 시도하게 된다.
    status: Mapped[str] = mapped_column(String(10), default=STATUS_OK)
    error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_sec_analyses_ticker", "ticker"),
        Index("ix_sec_analyses_created", "created_at"),
    )

    @property
    def cost_usd(self) -> float:
        """화면·로그 표시용. 계산에는 정수 필드를 쓴다."""
        return self.cost_micro_usd / 1_000_000

    def __repr__(self) -> str:
        return (
            f"<SecAnalysis {self.ticker} FY{self.fiscal_year} "
            f"{self.status} {self.accession_no}>"
        )
