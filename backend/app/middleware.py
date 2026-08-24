"""요청을 감싸는 미들웨어.

**순수 ASGI 미들웨어로 쓴다.** FastAPI 의 `@app.middleware("http")` 데코레이터는
Starlette 의 `BaseHTTPMiddleware` 를 씌우는데, 그것은 요청마다 anyio 작업 그룹과
메모리 스트림을 만들어 응답을 중계한다. 편하지만 대가가 있다 —

- 응답을 한 번 버퍼링하므로 스트리밍·백그라운드 작업과 상성이 나쁘다.
- **예외 전파 경로가 한 겹 더 생겨 간헐적으로 500 이 샌다.** 실제로 이 프로젝트에서
  겪었다: 이 파일로 옮기기 전, 같은 요청 120번 중 5번이 무작위로 500 이 됐다.
  순수 ASGI 로 바꾼 뒤 그 실패가 사라졌다.

순수 ASGI 는 `send` 만 감싸므로 중계 계층이 없고, 하는 일도 "상태 코드를 엿본다"뿐이라
BaseHTTPMiddleware 를 쓸 이유가 없었다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.services import health as health_service

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class ServerErrorRecorder:
    """5xx 를 기록해 둔다. 가동 상태 판단과 알림이 이 기록을 근거로 쓴다.

    로그(journalctl)에도 남지만 사람이 서버에 들어가 봐야 보인다. 앱이 스스로
    "최근 30분에 오류가 몇 건 났다"고 답할 수 있어야 알림을 보낼 수 있다.

    **예외를 삼키지 않는다.** 잡아서 기록만 하고 그대로 다시 던진다 — FastAPI 의
    기본 처리(500 응답 + 스택트레이스 로그)가 그대로 일어나야 한다.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # 수명주기(lifespan)·웹소켓은 그대로 흘려보낸다.
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def watched_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start" and message["status"] >= 500:
                health_service.record_error(path, message["status"], "")
            await send(message)

        try:
            await self.app(scope, receive, watched_send)
        except Exception as exc:
            # 여기까지 올라온 예외는 응답이 시작되기 전에 터진 것이라 위 send 가 못 본다.
            health_service.record_error(path, 500, f"{type(exc).__name__}: {exc}")
            raise
