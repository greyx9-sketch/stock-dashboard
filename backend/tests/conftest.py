"""pytest 공통 설정.

`app` 패키지를 찾을 수 있도록 `backend` 를 경로에 넣는다. 프로젝트에 별도 패키징 설정이
없어서(설치 없이 uvicorn 으로 바로 띄운다) 테스트에서도 같은 방식으로 맞춘다.

**이 테스트들은 네트워크를 부르지 않고 진짜 키도 필요 없다.** 순수 함수를 직접 부르거나,
외부를 부르는 지점을 가짜로 바꾼 뒤 라우터를 부른다.

외부 API 응답에 의존하는 확인은 `backend/scripts/check_*.py` 스크립트가 맡는다 —
그쪽은 실제 문서를 받아 눈으로 보는 용도이고, 이쪽은 되돌아오지 않아야 하는 것을 못 박는 용도다.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import httpx

# 배포 서버(리눅스)와 같은 이벤트 루프를 쓴다. Windows 기본값인 Proactor 루프는
# 정리될 때 `ProactorEventLoop object has no attribute '_ssock'` 을 뿜는다.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ---------------------------------------------------------------- 이벤트 루프 하나만
#
# **이 개발 PC 에서는 이벤트 루프를 12개째 만들 때 실패한다.**
#
#     OSError: [WinError 10014] ... 잘못된 포인터 주소를 감지했습니다
#     (asyncio 가 루프마다 만드는 self-pipe 소켓의 listen() 에서 난다)
#
# 백신·방화벽이 루프백 소켓 생성에 끼어드는 것으로 보이며, 우리 코드로는 어쩔 수 없다.
# 실제로 이것 때문에 테스트가 오랫동안 간헐적으로 깨졌다 — 매번 다른 테스트가, 본문이 빈
# 500 으로. 원인을 모른 채로 "또 그거겠지" 하고 넘기게 되는 종류의 실패다.
#
# 그래서 **세션 전체가 루프 하나를 나눠 쓴다.** 비동기 코드를 부를 일이 있으면
# `asyncio.run()` 대신 `run_async()` 를 쓴다.

_LOOP: asyncio.AbstractEventLoop | None = None


def get_loop() -> asyncio.AbstractEventLoop:
    """세션이 공유하는 이벤트 루프. 없으면 그때 하나 만든다."""
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP


def run_async(coro):
    """코루틴 하나를 공유 루프에서 돌린다. `asyncio.run()` 을 쓰지 않는 이유는 위 참고."""
    return get_loop().run_until_complete(coro)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# **테스트는 진짜 DB 를 건드리지 않는다.** `app.models.base` 는 import 시점에 엔진을 만들므로
# 앱을 부르기 전에 여기서 주소를 바꿔 둬야 한다. 이 파일은 pytest 가 가장 먼저 읽는다.
os.environ["DATABASE_URL"] = "sqlite:///" + (
    Path(tempfile.mkdtemp(prefix="stock-test-")) / "test.db"
).as_posix()

# 라우터가 토스 클라이언트를 만들 수 있어야 한다. 실제로 호출하지는 않는다 —
# 외부를 부르는 지점은 테스트에서 전부 가짜로 바꾼다.
os.environ.setdefault("TOSS_CLIENT_ID", "test-id")
os.environ.setdefault("TOSS_CLIENT_SECRET", "test-secret")


# ---------------------------------------------------------------- HTTP 테스트 클라이언트


class AsgiTestClient:
    """앱을 직접 부르는 얇은 클라이언트. Starlette 의 `TestClient` 대신 쓴다.

    **왜 TestClient 를 쓰지 않는가.** 지금 설치된 조합(starlette 1.6 + httpx 0.28)에서
    TestClient 는 요청 수십~수백 번에 한 번꼴로 **본문이 빈 500** 을 돌려준다. 앱이 아니라
    TestClient 의 중계 스레드 쪽 문제다 — 우리 5xx 기록 미들웨어에도 아무것도 안 남는다.
    starlette 스스로 "httpx 대신 httpx2 를 쓰라"는 경고를 띄우는 조합이기도 하다.

    실측: 같은 요청 400회에서 TestClient 는 최대 28회 실패, 이 클라이언트는 0회.

    **간헐적으로 실패하는 테스트는 없느니만 못하다.** 며칠이면 "또 그거겠지" 하고 넘기게
    되고, 그때부터는 진짜 회귀도 같이 묻힌다. 그래서 우회하지 않고 전송 계층을 바꿨다.

    `httpx.ASGITransport` 는 중계 스레드 없이 ASGI 앱을 그대로 호출한다.
    `raise_app_exceptions=False` 는 TestClient 의 `raise_server_exceptions=False` 와 같다 —
    앱이 터지면 예외를 올리지 않고 500 응답으로 만든다(오류 처리 경로를 테스트하려면 필요).
    """

    def __init__(self, app) -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        )

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        return run_async(self._client.request(method, url, **kwargs))

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def close(self) -> None:
        """httpx 클라이언트만 닫는다. **루프는 닫지 않는다** — 세션이 공유하는 것이다."""
        run_async(self._client.aclose())
