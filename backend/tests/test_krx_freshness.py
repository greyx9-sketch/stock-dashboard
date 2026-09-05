"""KRX 응답 신선도 가드.

**비어 있는지만 보는 검사는 비어 있지 않은 틀린 값을 못 잡는다.** 이 파일은 그 빈틈을
못 박는다 — 응답에 행이 있고 종가도 차 있지만, 그 행이 **우리가 요청한 날짜의 것이
아닐 때** 무슨 일이 벌어져야 하는가.

왜 미리 넣는가: 우리 테스트는 "실제로 겪은 버그를 회귀로" 쌓아 왔는데, 이건 남이 겪은
버그다(`docs/외부저장소조사.md` B-2). TradingAgents 는 yfinance 가 이따금 1년 전
프레임을 돌려주는 것에 당했다 — 행도 있고 Close 도 있어서 빈 값 검사를 통과했고,
**틀린 종가가 조용히 리포트에 들어갔다.**
"""

from __future__ import annotations

from datetime import date

import pytest

from app.clients.krx import KrxClient, KrxError
from tests.conftest import run_async

DAY = date(2026, 9, 4)


def _row(bas_dt: str, symbol: str = "005930", close: str = "70000") -> dict[str, str]:
    """포털 응답 한 줄의 최소 형태. 가드가 보는 것은 `basDt` 뿐이다."""
    return {
        "basDt": bas_dt,
        "srtnCd": symbol,
        "isinCd": f"KR7{symbol}003",
        "itmsNm": "삼성전자",
        "mrktCtg": "KOSPI",
        "clpr": close,
        "vs": "100",
        "fltRt": ".14",
        "mkp": close,
        "hipr": close,
        "lopr": close,
        "trqu": "1000",
        "trPrc": "70000000",
        "lstgStCnt": "5969782550",
        "mrktTotAmt": "417884778500000",
    }


def test_matching_rows_pass_through():
    """정상 경로 — 요청한 날짜의 행은 그대로 지나간다."""
    rows = [_row("20260904", "005930"), _row("20260904", "000660")]
    assert KrxClient._only_for(rows, DAY) == rows


def test_holiday_empty_response_is_not_an_error():
    """휴장일은 빈 목록으로 온다. 이걸 오류로 만들면 공휴일마다 수집이 실패한다."""
    assert KrxClient._only_for([], DAY) == []


def test_all_rows_from_another_day_stop_the_run():
    """**요청한 날짜가 한 줄도 없으면 저장하지 않고 멈춘다.**

    포털이 `basDt` 를 무시하고 다른 날을 돌려주는 상황이다. 그냥 저장하면 데이터 자체는
    맞지만 적재 보고가 거짓이 되고(`DayResult` 는 요청한 날짜를 들고 있다), 그날은
    영영 비어 있는 것으로 보여 **매일 같은 날을 다시 받는다** — 일일 한도 10,000 건이
    조용히 샌다. 값을 지어내지 말고 이유를 말하며 멈추는 편이 정직하다.
    """
    rows = [_row("20250904"), _row("20250904", "000660")]  # 1년 전
    with pytest.raises(KrxError) as err:
        KrxClient._only_for(rows, DAY)
    # 어느 날짜가 왔는지 메시지에 남아야 서버에 들어가지 않고도 짐작할 수 있다.
    assert "20250904" in str(err.value)
    assert "2026-09-04" in str(err.value)


def test_mixed_days_keep_only_the_requested_one():
    """일부만 섞여 있으면 맞는 것만 남긴다. 하루치가 통째로 날아가는 것이 더 나쁘다."""
    rows = [_row("20260904", "005930"), _row("20260903", "000660")]
    kept = KrxClient._only_for(rows, DAY)
    assert kept == [rows[0]]


def test_blank_date_row_is_dropped():
    """`basDt` 가 빈 행은 버린다.

    그냥 저장하면 `trade_date=""` 인 행이 기본키로 들어앉는다. 화면의 "가장 오래된
    거래일"이 빈 문자열이 되고, 날짜로 거는 조회가 전부 그 행을 스쳐 간다.
    """
    rows = [_row("20260904"), _row("", "000660")]
    assert KrxClient._only_for(rows, DAY) == [rows[0]]


# ---------------------------------------------------------------- 기간 조회 쪽
#
# `get_daily_quotes` 는 창(begin~end)을 주고 받은 뒤 **정렬해서 맨 앞을 집는다.**
# 창 밖의 오래된 행이 섞여 들어오면 그게 곧 "가장 최근 종가"가 된다.


def _fake_request(rows):
    async def _request(self, path, params):
        return rows

    return _request


def test_out_of_window_rows_cannot_become_the_latest_close(monkeypatch):
    """**1년 전 행이 '가장 최근 종가' 자리를 차지하지 못한다.**"""
    rows = [_row("20260903"), _row("20250115", close="50000")]
    monkeypatch.setattr(KrxClient, "_request", _fake_request(rows))

    client = KrxClient.__new__(KrxClient)  # 네트워크·키 없이 메서드만 부른다
    quotes = run_async(
        client.get_daily_quotes("005930", begin=date(2026, 9, 1), end=date(2026, 9, 4))
    )

    assert [q.trade_date for q in quotes] == ["2026-09-03"]
