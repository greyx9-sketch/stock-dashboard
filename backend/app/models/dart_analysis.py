"""사업보고서 서술 분석 결과 저장.

미국 쪽 `us_analysis.py` 의 국내판이다. 표를 나눈 이유는 프로젝트의 다른 곳과 같다 —
조회 열쇠가 다르고(접수번호 vs 접수번호지만 체계가 다름, 고유번호 vs CIK), 문서 서식이
다르고, 뽑아내는 절의 이름 자체가 다르다. 한 표에 억지로 합치면 어느 규칙으로 읽어야
하는지 알 수 없는 행이 생긴다.

기본키를 (접수번호, 모델, 프롬프트 버전) 으로 잡은 것도 같다. 같은 보고서를 두 번
분석하지 않는 근거가 이 키다.

수치 열이 없는 것도 같다(절대 규칙 3). 매출·이익은 XBRL 에서 계산해 `financials`
쪽에 들어가고, 여기에는 LLM 이 쓴 문장만 담는다.
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


class DartAnalysis(Base):
    """사업보고서 한 건에 대한 서술 분석 결과."""

    __tablename__ = "dart_analyses"

    receipt_no: Mapped[str] = mapped_column(String(14), primary_key=True)
    model: Mapped[str] = mapped_column(String(40), primary_key=True)
    prompt_version: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 어느 문서인지
    corp_code: Mapped[str] = mapped_column(String(8))
    stock_code: Mapped[str] = mapped_column(String(6))
    corp_name: Mapped[str] = mapped_column(String(200), default="")
    # 보고서 이름 그대로 남긴다. "[기재정정]사업보고서 (2025.12)" 처럼 정정 여부가
    # 이름에 드러나므로, 화면에서 어떤 판을 분석했는지 밝힐 수 있다.
    report_name: Mapped[str] = mapped_column(String(200), default="")
    fiscal_year: Mapped[int] = mapped_column(Integer, default=0)
    received_date: Mapped[str] = mapped_column(String(10), default="")  # YYYY-MM-DD
    source_url: Mapped[str] = mapped_column(String(400), default="")

    content_json: Mapped[str] = mapped_column(Text, default="")

    # 어떤 절을 실제로 넣었는지 / 길이 상한에 걸려 잘린 절.
    # 없는 것을 있는 척하지 않기 위해 화면에서 밝힌다.
    sections: Mapped[str] = mapped_column(String(120), default="")
    truncated: Mapped[str] = mapped_column(String(120), default="")

    # 사업의 내용·투자자 보호사항을 어느 분·반기보고서에서 가져왔는지. 비어 있으면
    # 사업보고서 것만 썼다는 뜻이다.
    #
    # 화면 각주에 "어느 시점 자료인가"를 밝히고, **새 분·반기보고서가 나왔는지 판단**
    # 하는 데 쓴다(`_should_rerun`). server_default 를 반드시 준다 — 없으면 SQLite 가
    # 기존 표에 컬럼 붙이기를 거절한다(2026-09-01 사고, tests/test_schema_sync.py 참고).
    recent_receipt_no: Mapped[str] = mapped_column(String(20), default="", server_default="")
    recent_report_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    recent_received_date: Mapped[str] = mapped_column(String(10), default="", server_default="")

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_micro_usd: Mapped[int] = mapped_column(Integer, default=0)

    # 배치로 맡겼을 때의 배치 id. 이 값이 있고 status 가 pending 이면 결과를 기다리는
    # 중이다. 끝나도 지우지 않고 남겨 둔다 — 어느 배치에서 나온 결과인지 나중에 추적할 수 있게.
    # `server_default` 가 **꼭 있어야 한다.** 파이썬 쪽 `default=` 는 DDL 에 안 나타나서,
    # 이미 행이 있는 표에 NOT NULL 컬럼을 붙일 때 SQLite 가 "기존 행은 뭘로 채우냐"며
    # 거절한다. 그러면 `schema_sync` 가 경고만 남기고 넘어가고, 그 뒤 이 표를 읽는
    # 모든 조회가 `no such column` 500 이 된다 — 실제로 한 번 그렇게 배포했다.
    batch_id: Mapped[str] = mapped_column(String(64), default="", server_default="")

    status: Mapped[str] = mapped_column(String(10), default=STATUS_OK)
    error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_dart_analyses_stock", "stock_code"),
        Index("ix_dart_analyses_created", "created_at"),
    )

    @property
    def cost_usd(self) -> float:
        return self.cost_micro_usd / 1_000_000

    def __repr__(self) -> str:
        return (
            f"<DartAnalysis {self.stock_code} {self.corp_name} "
            f"FY{self.fiscal_year} {self.status}>"
        )
