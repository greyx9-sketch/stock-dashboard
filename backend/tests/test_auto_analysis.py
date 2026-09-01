"""새 연차보고서 자동 분석 회귀 테스트.

**이 기능은 돈을 쓴다.** 문서 한 건에 200~340원이고, 사람이 시키지 않았는데 나간다.
그래서 여기서 지키는 것의 대부분은 "얼마나 잘 분석하는가"가 아니라 **얼마나 안 쓰는가**다:

1. **사람 몫을 남긴다.** 자동 분석이 하루 상한을 다 쓰면, 사용자가 직접 누르려던 분석이
   자기가 시키지도 않은 일 때문에 막힌다.
2. **한 번에 세 건까지.** 3월처럼 여러 회사가 한꺼번에 보고서를 내도 나눠서 한다.
3. **이미 분석한 것은 다시 부르지 않는다.** 그 판단은 `analyze()` 안에 있지만, 자동
   경로가 그것을 우회하지 않는지 여기서 확인한다.

**모델을 실제로 부르지 않는다.** 테스트가 돈을 쓰면 안 되고, 결과가 그날 사정에 따라
달라져서도 안 된다. 분석 함수를 갈아 끼우고 **부른 횟수**만 센다.

2026-09-01 부터 자동 분석은 **배치로 맡기고 끝난다**(반값, 최대 24시간). 그래서 여기서
세는 것은 "몇 건을 분석했나"가 아니라 **"몇 건을 맡겼나"**다. 울타리(사람 몫 5건,
한 번에 3건)는 그대로이고, 오히려 더 중요해졌다 — 맡긴 순간 돈이 확정되기 때문이다.
"""

from __future__ import annotations

import pytest

from app.models.base import get_session, init_db
from app.models.watchlist import WatchlistItem
from app.services import auto_analysis
from tests.conftest import run_async


class _FakeClient:
    """배치 클라이언트 자리. 아무것도 하지 않고 닫히기만 한다."""

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _clean():
    init_db()
    with get_session() as session:
        session.query(WatchlistItem).delete()
        session.commit()


def _watch(*symbols: str) -> None:
    with get_session() as session:
        for order, symbol in enumerate(symbols):
            session.add(
                WatchlistItem(
                    symbol=symbol,
                    market="KR" if symbol.isdigit() else "US",
                    name=symbol,
                    sort_order=order,
                )
            )
        session.commit()


class _Spy:
    """준비 함수를 대신한다. 무엇을 몇 번 불렀는지만 센다.

    `submitted` 면 배치 요청 한 건을 함께 돌려준다 — `run()` 이 그것을 모아 제출한다.
    """

    def __init__(self, outcome: str = "submitted"):
        self.calls: list[str] = []
        self.outcome = outcome

    async def __call__(self, symbol: str):
        self.calls.append(symbol)
        if self.outcome != "submitted":
            return self.outcome, "", None
        return self.outcome, f"us:{symbol}", {"custom_id": f"us:{symbol}"}


async def _fake_submit(client, requests):
    return "batch-테스트"


def _run(monkeypatch, spy, *, calls_today: int = 0, limit: int = 20):
    monkeypatch.setattr(auto_analysis, "_prepare_one", spy)
    # **배치 제출을 실제로 하지 않는다.** 테스트가 돈을 쓰면 안 된다.
    monkeypatch.setattr(auto_analysis.analysis_batch, "submit", _fake_submit)
    monkeypatch.setattr(auto_analysis.analysis_batch, "new_client", lambda: _FakeClient())
    monkeypatch.setattr(auto_analysis, "_mark_submitted", lambda *a: None)
    monkeypatch.setattr(auto_analysis.llm_budget, "calls_today", lambda: calls_today)
    monkeypatch.setattr(
        auto_analysis, "get_settings", lambda: type("S", (), {"analysis_daily_limit": limit})()
    )
    return run_async(auto_analysis.run())


# ---------------------------------------------------------------- 예산 울타리


def test_manual_share_is_always_left(monkeypatch):
    """**이 파일에서 가장 중요한 테스트.**

    상한 20건에 오늘 15건을 썼으면 남은 5건은 사람 몫이다. 자동 분석은 손대지 않는다.
    """
    _watch("005930", "AAPL")
    spy = _Spy()
    report = _run(monkeypatch, spy, calls_today=15, limit=20)

    assert spy.calls == [], "사람 몫을 자동 분석이 썼다"
    assert "남겨" in (report.stopped_reason or "")


def test_budget_left_counts_the_reserve():
    """남은 몫 계산 자체를 못 박는다 — 상한 20, 오늘 10건이면 자동은 5건까지."""
    from app.config import get_settings

    limit = get_settings().analysis_daily_limit
    assert auto_analysis.MANUAL_RESERVE == 5
    assert auto_analysis.budget_left() <= max(limit - 5, 0)


def test_at_most_three_per_run(monkeypatch):
    """3월에 여러 회사가 한꺼번에 내도 며칠에 나눠 한다."""
    _watch("005930", "000660", "035720", "AAPL", "MSFT")
    spy = _Spy()
    report = _run(monkeypatch, spy)

    assert len(report.submitted) == auto_analysis.MAX_PER_RUN == 3
    assert len(spy.calls) == 3
    assert "3건" in (report.stopped_reason or "")


def test_already_analyzed_does_not_count_against_the_run(monkeypatch):
    """이미 있는 것은 API 를 부르지 않으므로 건수에 넣지 않는다.

    넣어 버리면 관심종목 앞쪽 세 개가 이미 분석돼 있을 때 뒤쪽의 **새 보고서를 영영
    못 본다.**
    """
    _watch("005930", "000660", "035720", "AAPL", "MSFT")
    spy = _Spy(outcome="already")
    report = _run(monkeypatch, spy)

    assert spy.calls == ["005930", "000660", "035720", "AAPL", "MSFT"]
    assert report.already_had == 5
    assert report.submitted == []
    assert report.stopped_reason is None


# ---------------------------------------------------------------- 멈추지 않기


def test_one_failure_does_not_stop_the_rest(monkeypatch):
    """ETF·상장폐지처럼 분석할 문서가 없는 종목이 섞여 있다."""
    _watch("005930", "AAPL")

    async def _flaky(symbol: str):
        if symbol == "005930":
            raise RuntimeError("보고서 없음")
        return "submitted", "us:AAPL", {"custom_id": "us:AAPL"}

    report = _run(monkeypatch, _flaky)
    assert report.submitted == ["AAPL"]
    assert len(report.failed) == 1


def test_empty_watchlist_does_nothing(monkeypatch):
    """관심종목이 비어 있으면 아무 일도 하지 않는다 — 돈도 안 쓴다."""
    spy = _Spy()
    report = _run(monkeypatch, spy)
    assert spy.calls == []
    assert report.checked == 0


def test_symbols_without_documents_are_recorded_not_failed(monkeypatch):
    """문서가 없는 것과 실패한 것은 다르다. 뭉치면 원인을 못 찾는다."""
    _watch("SOXL")
    spy = _Spy(outcome="no-report")
    report = _run(monkeypatch, spy)

    assert report.skipped_no_report == ["SOXL"]
    assert report.failed == []


# ---------------------------------------------------------------- 종목 갈래


def test_korean_and_us_symbols_go_to_different_analysers(monkeypatch):
    """6자리 숫자는 국내(사업보고서), 나머지는 미국(10-K)이다."""
    seen: list[tuple[str, str]] = []

    async def _fake_dart_prepare(corp):
        seen.append(("KR", corp.stock_code))
        return {"custom_id": f"kr:{corp.stock_code}"}

    async def _fake_tenk_prepare(company):
        seen.append(("US", company.ticker))
        return {"custom_id": f"us:{company.ticker}"}

    monkeypatch.setattr(auto_analysis.dart_analysis, "prepare_batch", _fake_dart_prepare)
    monkeypatch.setattr(auto_analysis.tenk_analysis, "prepare_batch", _fake_tenk_prepare)
    monkeypatch.setattr(auto_analysis.analysis_batch, "submit", _fake_submit)
    monkeypatch.setattr(auto_analysis.analysis_batch, "new_client", lambda: _FakeClient())
    monkeypatch.setattr(auto_analysis, "_mark_submitted", lambda *a: None)
    monkeypatch.setattr(
        auto_analysis.dart_corps, "get_corp",
        lambda s: type("C", (), {"stock_code": s, "corp_code": "0" * 8})(),
    )
    monkeypatch.setattr(
        auto_analysis.sec_companies, "get_company",
        lambda s: type("C", (), {"ticker": s, "cik": "0" * 10})(),
    )

    _watch("005930", "AAPL")
    run_async(auto_analysis.run())
    assert seen == [("KR", "005930"), ("US", "AAPL")]
