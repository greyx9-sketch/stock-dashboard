"""라우터 통합 테스트 — 경로가 제대로 잡히는지, 잘못된 입력을 제대로 거절하는지.

순수 함수 테스트가 못 잡는 종류의 실수를 여기서 잡는다. 실제로 이 프로젝트에서
겪은 것들이다:

  - **경로 순서.** `/{symbol}` 포괄 경로를 먼저 등록하면 `/search` 나 `/analysis` 를
    종목 코드로 오인해 삼켜 버린다. 라우터 등록 순서 한 줄로 조용히 깨진다.
  - **입력 제약.** `/api/prices` 의 `min_length=6` 때문에 미국 티커 단건 조회(KO·AAPL)가
    422 로 거절됐다. KRX 코드가 6자리라 맞는 값처럼 보였고, 여러 종목이면 콤마 때문에
    길어져 우연히 통과해서 늦게 드러났다.
  - **상태 코드 매핑.** 없는 종목을 502(서버 오류)로 돌리면 원인을 잘못 짚게 된다.

**네트워크는 부르지 않는다.** 외부를 부르는 서비스 함수는 전부 가짜로 바꾼다.
DB 는 conftest 가 임시 파일로 돌려 둔다 — 진짜 DB 를 건드리지 않는다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.main import app
from app.models.base import init_db
from app.services import flows as flows_service
from app.services import watchlist as watchlist_service
from tests.conftest import AsgiTestClient


@pytest.fixture(scope="module")
def client():
    """lifespan 을 켜지 않는다. 켜면 시세 폴러와 스케줄러가 떠서 외부를 부른다.

    클라이언트는 `conftest.AsgiTestClient` 다 — Starlette 의 TestClient 를 쓰지 않는
    이유는 그쪽 docstring 에 적어 두었다.
    """
    init_db()
    made = AsgiTestClient(app)
    yield made
    made.close()


# ---------------------------------------------------------------- 경로 순서


def test_search_is_not_swallowed_by_the_symbol_route(client):
    """`/api/stocks/search` 가 `/{symbol}` 에 먼저 잡히면 6자리가 아니라며 422 가 된다.

    테스트 DB 는 비어 있으므로 검색 자체는 503("DB 에 시세가 없습니다")으로 끝난다.
    그래도 **검색 처리기까지 도달했다**는 것이 여기서 확인하려는 것이다 —
    422 가 나오면 포괄 경로에 먹힌 것이고, 그것이 실제로 겪은 실수다.
    """
    response = client.get("/api/stocks/search?q=삼성")
    assert response.status_code != 422
    assert "시세가 없습니다" in response.text or response.status_code == 200


def test_kr_analysis_path_is_not_read_as_a_symbol(client):
    """`/api/stocks/005930/analysis` 가 종목 상세 경로에 밀리지 않는지.

    두 처리기는 실패 문구가 다르다 — 상세는 "시세가 DB 에 없습니다", 분석은 "DART 매핑에서
    찾지 못했습니다". 문구로 어디까지 갔는지 가른다.
    """
    response = client.get("/api/stocks/005930/analysis")
    assert "DART" in response.text


def test_us_usage_path_is_not_read_as_a_ticker(client):
    """`/api/us/analysis/usage` 가 `/{ticker}` 에 먼저 잡히면 analysis 를 티커로 읽는다."""
    response = client.get("/api/us/analysis/usage")
    assert response.status_code == 200
    # 국내·미국 합산 사용량이다. 지갑이 하나이므로 상한도 하나다.
    assert response.json()


def test_unknown_api_path_is_404_not_the_spa(client):
    """없는 API 를 부르면 화면(index.html)이 200 으로 돌아오면 안 된다 —
    오류를 알아챌 수 없게 된다."""
    assert client.get("/api/nope").status_code == 404


# ---------------------------------------------------------------- 입력 제약


def test_single_us_ticker_price_is_allowed(client):
    """예전에 min_length=6 때문에 거절됐다. 화면에는 현재가 연결 끊김으로 보였다."""
    for symbol in ("KO", "AAPL"):
        response = client.get(f"/api/prices?symbols={symbol}")
        # 실패하면 본문까지 남긴다. 상태 코드만 보면 무엇이 막았는지 알 수 없다.
        assert response.status_code == 200, f"{symbol}: {response.status_code} {response.text[:200]}"


def test_kr_symbol_price_still_works(client):
    assert client.get("/api/prices?symbols=005930").status_code == 200
    assert client.get("/api/prices?symbols=005930,000660").status_code == 200


def test_empty_symbols_is_rejected(client):
    assert client.get("/api/prices?symbols=").status_code == 422


@pytest.mark.parametrize("bad", ["AAPL", "12345", "1234567", "005930x"])
def test_flows_rejects_non_kr_symbols(client, bad):
    """수급은 국내 전용이다. 미국 티커로 부르면 서버 오류가 아니라 입력 오류다."""
    assert client.get(f"/api/stocks/{bad}/flows").status_code == 422


def test_flows_rejects_too_many_days(client):
    assert client.get("/api/stocks/005930/flows?days=999").status_code == 422


# ---------------------------------------------------------------- 상태 코드 매핑


def test_missing_stock_in_flows_is_404_not_502(client, monkeypatch):
    """토스가 없는 종목이라고 말해 주면 502 가 아니라 404 로 옮긴다."""

    async def fake(symbol, *, days=5):
        return flows_service.Flows(
            symbol=symbol, errors=["투자자별 매매동향: stock-not-found"]
        )

    monkeypatch.setattr(flows_service, "get_flows", fake)
    response = client.get("/api/stocks/999999/flows")
    assert response.status_code == 404
    assert "찾을 수 없습니다" in response.json()["detail"]


def test_total_failure_in_flows_is_502(client, monkeypatch):
    """진짜로 못 받은 경우는 서버 쪽 문제로 알린다."""

    async def fake(symbol, *, days=5):
        return flows_service.Flows(symbol=symbol, errors=["투자자별 매매동향: 연결 실패"])

    monkeypatch.setattr(flows_service, "get_flows", fake)
    assert client.get("/api/stocks/005930/flows").status_code == 502


def test_partial_failure_still_returns_200(client, monkeypatch):
    """다섯 중 하나가 없다고 수급 블록 전체가 사라지면 고장으로 읽힌다."""

    async def fake(symbol, *, days=5):
        return flows_service.Flows(
            symbol=symbol,
            metrics=[flows_service.Metric(label="공매도 비중", value="5.88", unit="%")],
            errors=["신용거래: 연결 실패"],
        )

    monkeypatch.setattr(flows_service, "get_flows", fake)
    response = client.get("/api/stocks/005930/flows")
    assert response.status_code == 200
    assert len(response.json()["metrics"]) == 1
    assert response.json()["errors"]


# ---------------------------------------------------------------- 관심종목 (쓰기 경로)


@pytest.fixture
def no_network_watchlist(monkeypatch):
    """이름 조회와 미국 기준가만 가짜로 바꾼다. DB 쓰기는 진짜로 돈다(임시 DB)."""

    async def fake_name(symbol: str) -> str:
        if symbol == "ZZZZ":
            raise watchlist_service.WatchlistError(f"'{symbol}' 을 찾을 수 없습니다.")
        return {"005930": "삼성전자", "AAPL": "애플"}.get(symbol, symbol)

    async def fake_us_bases(symbols):
        return {s: (Decimal("305.93"), "2026-08-14") for s in symbols}

    monkeypatch.setattr(watchlist_service, "_resolve_name", fake_name)
    monkeypatch.setattr(watchlist_service, "_us_bases", fake_us_bases)


def test_watchlist_round_trip(client, no_network_watchlist):
    client.delete("/api/watchlist/005930")
    client.delete("/api/watchlist/AAPL")

    assert client.post("/api/watchlist", json={"symbol": "005930"}).status_code == 200
    assert client.post("/api/watchlist", json={"symbol": "aapl"}).status_code == 200

    symbols = [i["symbol"] for i in client.get("/api/watchlist").json()["items"]]
    # 소문자로 넣어도 대문자로 저장된다. 안 그러면 같은 종목이 두 줄이 된다.
    assert "AAPL" in symbols
    assert "005930" in symbols

    assert client.delete("/api/watchlist/AAPL").json() == {"removed": True}
    # 없는 것을 지워도 404 가 아니다 — 결과가 같기 때문이다.
    assert client.delete("/api/watchlist/AAPL").json() == {"removed": False}


def test_adding_twice_is_not_an_error(client, no_network_watchlist):
    """별을 연달아 눌러도 오류가 뜨면 안 된다."""
    client.delete("/api/watchlist/005930")
    first = client.post("/api/watchlist", json={"symbol": "005930"})
    second = client.post("/api/watchlist", json={"symbol": "005930"})
    assert first.status_code == second.status_code == 200
    assert second.json()["symbol"] == "005930"


def test_unknown_symbol_is_400_with_a_readable_reason(client, no_network_watchlist):
    response = client.post("/api/watchlist", json={"symbol": "ZZZZ"})
    assert response.status_code == 400
    assert "찾을 수 없습니다" in response.json()["detail"]


def test_move_direction_is_validated(client, no_network_watchlist):
    client.post("/api/watchlist", json={"symbol": "005930"})
    response = client.post("/api/watchlist/005930/move", json={"direction": "sideways"})
    assert response.status_code == 400


def test_market_is_decided_when_adding(client, no_network_watchlist):
    client.delete("/api/watchlist/AAPL")
    assert client.post("/api/watchlist", json={"symbol": "AAPL"}).json()["market"] == "US"


# ---------------------------------------------------------------- 가동 상태


def test_health_detail_is_200_even_when_unhealthy(client):
    """이 응답 자체가 진단 결과다. 500 으로 돌려주면 내용을 읽을 수 없다."""
    response = client.get("/api/health/detail")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("ok", "degraded", "down")
    assert {c["name"] for c in body["checks"]} >= {"DB", "현재가", "종가 수집", "서버 오류"}


def test_plain_health_stays_simple(client):
    """배포 스크립트와 오라클 경보가 읽는 경로다. 모양이 바뀌면 안 된다."""
    assert client.get("/health").json() == {"status": "ok"}


# ---------------------------------------------------------------- 메모 (쓰기 경로)


def test_note_crud_round_trip(client):
    """메모는 지워지면 복구할 수 없는 유일한 데이터다. 네 동작을 한 번에 확인한다."""
    created = client.post(
        "/api/notes", json={"symbol": "005930", "body": "첫 메모", "tags": ["반도체"]}
    )
    assert created.status_code == 201
    note_id = created.json()["id"]
    assert created.json()["tags"] == ["반도체"]
    assert created.json()["edited"] is False

    listed = client.get("/api/notes?symbol=005930").json()
    assert note_id in [n["id"] for n in listed]

    edited = client.put(f"/api/notes/{note_id}", json={"body": "고친 메모", "tags": []})
    assert edited.status_code == 200
    assert edited.json()["edited"] is True
    # 고쳤다고 작성 시각이 덮이면 안 된다 — 언제 그 판단을 했는지가 메모의 값어치다.
    assert edited.json()["created_at"] == created.json()["created_at"]

    assert client.delete(f"/api/notes/{note_id}").json() == {"removed": True}
    assert client.delete(f"/api/notes/{note_id}").json() == {"removed": False}


def test_empty_note_is_rejected(client):
    response = client.post("/api/notes", json={"symbol": "005930", "body": "   "})
    assert response.status_code in (400, 422)


def test_note_symbol_is_required(client):
    assert client.post("/api/notes", json={"body": "종목 없이"}).status_code == 422


def test_notes_of_other_symbols_do_not_leak(client):
    """다른 종목 메모가 섞이면 기록으로서 쓸모가 없어진다."""
    a = client.post("/api/notes", json={"symbol": "000660", "body": "하이닉스 메모"}).json()
    b = client.post("/api/notes", json={"symbol": "AAPL", "body": "애플 메모"}).json()

    only = [n["id"] for n in client.get("/api/notes?symbol=000660").json()]
    assert a["id"] in only
    assert b["id"] not in only

    client.delete(f"/api/notes/{a['id']}")
    client.delete(f"/api/notes/{b['id']}")
