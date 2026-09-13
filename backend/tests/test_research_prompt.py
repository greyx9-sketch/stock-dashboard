"""AI 리서치 지시서 테스트.

**프롬프트는 한 글자가 바뀌면 결과가 달라지는 물건이다.** 그런데 화면에서는 그게
안 보인다 — 글이 조금 이상해도 눈으로는 넘어간다. 그래서 여기서 못 박는 것은
"글이 나오는가"가 아니라 **무엇이 반드시 들어 있는가**다.

셋이 특히 중요하다.

  1. **읽는 법이 자료보다 앞에 온다.** 뒤에 두었더니 "아래 수치는…" 이라 적어 놓고
     정작 그 수치가 위에 있었다. 규칙은 읽기 전에 읽혀야 규칙이다.
  2. **정기보고서가 목록에 있다.** 최근순으로만 채웠더니 임원 지분 신고 아홉 건이
     자리를 먹고 사업보고서가 밀려났다. 기업 분석에서 가장 먼저 읽어야 할 문서다.
  3. **4분기가 파생값이라고 표시된다.** DART 에 4분기 보고서가 없어 우리가 빼서
     만든 값이다. 공시에 그대로 적힌 숫자인 척하면 안 된다.

네트워크는 부르지 않는다. DART·SEC 자리에 가짜를 끼운다.
"""

from __future__ import annotations

import pytest

from app.services import research_prompt as rp

from tests.conftest import run_async


# ---------------------------------------------------------------- 가짜 자료


class Row:
    """재무 한 줄. 서비스가 읽는 속성만 흉내 낸다."""

    def __init__(self, year, revenue, operating, net, quarter=None):
        self.fiscal_year = year
        self.quarter = quarter
        self.revenue = revenue
        self.operating_income = operating
        self.net_income = net
        self.total_assets = None
        self.total_equity = None
        self.period_end = f"{year}-12-31"


class Filing:
    def __init__(self, date, name, receipt):
        self.received_date = date
        self.report_name = name
        self.receipt_no = receipt

    @property
    def viewer_url(self) -> str:
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={self.receipt_no}"


# ---------------------------------------------------------------- 순수 함수


def test_rules_come_before_the_data():
    """읽는 법이 자료보다 **앞**에 와야 한다.

    뒤에 두면 "아래 수치는 공시 원자료입니다" 라고 적어 놓고 그 수치가 위에 있게 된다.
    실제로 그렇게 만들었다가 첫 시험에서 눈으로 잡았다.
    """
    text = rp._assemble("머리말", ["### 표\n내용"], "## 해 주실 일")

    assert text.index(rp.HEADER_RULES) < text.index("### 표")
    assert text.index("머리말") < text.index(rp.HEADER_RULES)
    assert text.index("## 해 주실 일") > text.index("### 표")


def test_empty_blocks_are_dropped():
    """자료가 없는 구획은 통째로 빠진다. 빈 제목만 남으면 "값이 0" 으로 읽힌다."""
    text = rp._assemble("머리말", ["", "### 있는 것\n1", ""], "지시")

    assert "### 있는 것" in text
    assert "\n\n\n" not in text


def test_repeated_report_names_are_collapsed():
    """같은 이름의 공시가 목록을 통째로 먹는 것을 막는다.

    삼성전자에서 실제로 겪었다 — 최근 15건 중 아홉 건이
    "임원ㆍ주요주주특정증권등소유상황보고서" 였다. 임원 한 사람의 지분 신고가
    기업 분석의 자리를 차지한 것이다.
    """
    items = [Filing(f"2026-09-{day:02d}", "임원ㆍ주요주주특정증권등소유상황보고서", f"{day}")
             for day in range(20, 10, -1)]
    items.append(Filing("2026-08-14", "반기보고서 (2026.06)", "x"))

    kept = rp._dedupe_by_name(items, 15)

    names = [item.report_name for item in kept]
    assert names.count("임원ㆍ주요주주특정증권등소유상황보고서") == 1
    assert "반기보고서 (2026.06)" in names


def test_corrected_filing_counts_as_the_same_report():
    """`[기재정정]` 이 붙어도 같은 서류다. 앞머리 대괄호를 떼고 견준다."""
    items = [
        Filing("2026-09-02", "[기재정정]분기보고서 (2026.03)", "a"),
        Filing("2026-05-15", "분기보고서 (2026.03)", "b"),
    ]

    kept = rp._dedupe_by_name(items, 15)

    assert len(kept) == 1
    assert kept[0].receipt_no == "a"  # 최신 것이 남는다


def test_fourth_quarter_is_derived_and_marked():
    """DART 에 4분기 보고서가 없다. 연간에서 1~3분기를 빼서 채우되 **파생이라고 밝힌다.**"""
    quarters = [Row(2025, 100, 10, 8, quarter=q) for q in (1, 2, 3)]
    annual = [Row(2025, 500, 60, 50)]

    points = rp._with_q4(quarters, annual)

    assert [(p[0], p[1]) for p in points] == [(2025, 1), (2025, 2), (2025, 3), (2025, 4)]
    year, quarter, revenue, operating, net, derived = points[-1]
    assert (revenue, operating, net) == (200, 30, 26)  # 500-300, 60-30, 50-24
    assert derived is True
    assert points[0][5] is False


def test_fourth_quarter_is_skipped_when_a_quarter_is_missing():
    """1~3분기가 다 있어야 뺄 수 있다. 하나라도 비면 4분기를 만들지 않는다 —
    없는 분기를 0으로 치면 4분기가 통째로 부풀려진다."""
    quarters = [Row(2025, 100, 10, 8, quarter=q) for q in (1, 3)]
    annual = [Row(2025, 500, 60, 50)]

    points = rp._with_q4(quarters, annual)

    assert all(p[1] != 4 for p in points)


def test_fourth_quarter_is_skipped_without_the_annual_row():
    quarters = [Row(2025, 100, 10, 8, quarter=q) for q in (1, 2, 3)]

    assert all(p[1] != 4 for p in rp._with_q4(quarters, []))


def test_derivation_keeps_none_instead_of_guessing():
    """연간 값이 비어 있으면 4분기도 비운다. 0 으로 채우면 적자로 읽힌다."""
    quarters = [Row(2025, 100, None, 8, quarter=q) for q in (1, 2, 3)]
    annual = [Row(2025, 500, 60, 50)]

    _, _, revenue, operating, _, _ = rp._with_q4(quarters, annual)[-1]

    assert revenue == 200
    assert operating is None


# ---------------------------------------------------------------- 지시문


@pytest.mark.parametrize("preset", sorted(rp.PRESETS))
def test_every_preset_orders_research_before_writing(preset):
    """**모든 지시문이 "먼저 조사하라" 를 담아야 한다.**

    이 화면이 존재하는 이유가 그것이다 — 우리 분석은 원문 밖으로 못 나가지만
    붙여넣는 쪽은 웹을 뒤질 수 있다. 조사를 안 시키면 자료를 정리해 옮기는 것으로 끝나고,
    그건 우리가 이미 하던 일이다.
    """
    ask = rp.PRESETS[preset]["ask"]

    assert "웹" in ask or "원문" in ask
    assert rp.PRESETS[preset]["label"]
    assert rp.PRESETS[preset]["hint"]


def test_unknown_preset_falls_back_instead_of_failing():
    """모르는 종류를 물으면 기본으로 답한다. 주소를 손으로 고친 사람에게 500 을 주지 않는다."""
    assert rp.PRESETS.get("없는것") is None
    assert rp.DEFAULT_PRESET in rp.PRESETS


# ---------------------------------------------------------------- 조립 전체


def test_kr_prompt_has_everything_a_report_needs(monkeypatch):
    """국내 지시서 한 장에 **숫자·원문 주소·시킬 일**이 모두 들어 있는가."""

    class Corp:
        corp_code = "00126380"
        corp_name = "삼성전자"

    monkeypatch.setattr(rp.dart_corps, "get_corp", lambda symbol: Corp())

    async def fake_ensure(*args, **kwargs):
        return "CFS", 6

    monkeypatch.setattr(rp.dart_financials, "ensure_financials", fake_ensure)
    monkeypatch.setattr(rp.dart_quarterly, "ensure_quarterly", fake_ensure)
    monkeypatch.setattr(
        rp.dart_financials, "load", lambda *a, **k: [Row(2025, 333_605, 43_601, 45_206)]
    )
    monkeypatch.setattr(
        rp.dart_quarterly,
        "load",
        lambda *a, **k: [Row(2025, 80_000, 10_000, 9_000, quarter=q) for q in (1, 2, 3)],
    )
    monkeypatch.setattr(rp.valuation_service, "compute", lambda *a, **k: None)

    class FakeDart:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_disclosures(self, corp_code, **kwargs):
            if kwargs.get("report_type") == "A":
                return [Filing("2026-03-10", "사업보고서 (2025.12)", "20260310002820")]
            return [Filing("2026-09-09", "임원ㆍ주요주주특정증권등소유상황보고서", "1")]

    monkeypatch.setattr(rp, "DartClient", FakeDart)

    prompt = run_async(rp.build_kr("005930", "report"))

    assert prompt.name == "삼성전자"
    # 정기보고서가 **자기 표**에 있어야 한다. 최근순 목록에 섞이면 밀려난다.
    assert "사업보고서 (2025.12)" in prompt.text
    assert "여기부터 읽으십시오" in prompt.text
    assert "20260310002820" in prompt.text
    # 숫자와 시킬 일.
    assert "333,605" in prompt.text
    assert "해 주실 일" in prompt.text
    # 못 담은 것을 조용히 넘기지 않는다.
    assert "밸류에이션" in prompt.missing
    assert any("정기보고서" in item for item in prompt.included)


def test_kr_prompt_refuses_an_unknown_symbol(monkeypatch):
    """모르는 종목이면 사유를 담은 오류를 올린다. 빈 지시서를 만들어 주지 않는다."""
    monkeypatch.setattr(rp.dart_corps, "get_corp", lambda symbol: None)

    with pytest.raises(rp.PromptError) as caught:
        run_async(rp.build_kr("999999"))

    assert "999999" in str(caught.value)
