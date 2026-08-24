"""5xx 기록 미들웨어 테스트.

이 미들웨어가 조용히 고장나면 **가동 알림이 통째로 눈이 먼다.** 앱은 500 을 뿜는데
`/api/health/detail` 은 "최근 오류 0건"이라고 답하고, 감시 스크립트도 아무 말을 하지 않는다.
고장을 알리려고 만든 장치가 정작 그때 침묵하는 것이라 없느니만 못하다.

작은 앱을 따로 만들어 시험한다. 진짜 앱에 일부러 터지는 경로를 붙이면 다른 테스트에
그 경로가 남는다.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.middleware import ServerErrorRecorder
from app.services import health

from tests.conftest import AsgiTestClient, run_async


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/boom")
    def boom():
        raise ValueError("일부러 낸 오류")

    @app.get("/bad-gateway")
    def bad_gateway():
        raise HTTPException(status_code=502, detail="외부 API 가 응답하지 않습니다")

    @app.get("/fine")
    def fine():
        return {"ok": True}

    @app.get("/not-found")
    def not_found():
        raise HTTPException(status_code=404, detail="없습니다")

    app.add_middleware(ServerErrorRecorder)

    health._errors.clear()
    made = AsgiTestClient(app)
    yield made
    made.close()
    health._errors.clear()


def test_unhandled_exception_is_recorded(client):
    assert client.get("/boom").status_code == 500
    recorded = health.recent_errors()
    assert len(recorded) == 1
    assert recorded[0].path == "/boom"
    assert recorded[0].status == 500
    # 무엇이 터졌는지가 남아야 서버에 들어가지 않고도 짐작할 수 있다.
    assert "ValueError" in recorded[0].detail


def test_upstream_failure_status_is_recorded(client):
    """502 는 예외가 아니라 정상적으로 만들어진 응답이다. 그것도 세야 한다 —
    외부 API 가 죽으면 우리 화면도 죽은 것이나 마찬가지다."""
    assert client.get("/bad-gateway").status_code == 502
    assert [e.status for e in health.recent_errors()] == [502]


def test_success_and_client_errors_are_not_recorded(client):
    """404·422 는 사용자가 잘못 부른 것이지 앱 고장이 아니다.
    이것까지 세면 경보가 늘 울려 진짜 고장이 묻힌다."""
    client.get("/fine")
    client.get("/not-found")
    assert health.recent_errors() == []


def test_exception_is_not_swallowed(client):
    """예외를 삼키면 FastAPI 의 기본 처리(스택트레이스 로그)가 사라진다.
    기록만 하고 그대로 다시 던져야 한다."""
    app = FastAPI()

    @app.get("/boom")
    def boom():
        raise ValueError("올라와야 한다")

    app.add_middleware(ServerErrorRecorder)

    # raise_app_exceptions=True 면 예외가 그대로 올라온다.
    async def call():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            await c.get("/boom")

    with pytest.raises(ValueError, match="올라와야 한다"):
        run_async(call())


def test_recording_survives_many_requests(client):
    """오류가 쏟아져도 메모리를 계속 먹지 않는다(서버 메모리가 1GB 다)."""
    for _ in range(health.ERROR_BUFFER + 20):
        client.get("/boom")
    assert len(health._errors) == health.ERROR_BUFFER
