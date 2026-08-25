"""앱 로그를 실제로 보이게 한다.

**이 파일이 없으면 우리가 심어 둔 로그가 전부 사라진다.** 2026-08-25 에 서버를 점검하다
발견했다 — journalctl 에 uvicorn 의 접근 기록만 있고, "토스 웹소켓 연결됨" · "유니버스
적재 완료 — 종목 300" · "컬럼 추가" 같은 줄이 하나도 없었다.

이유는 단순하다. 각 모듈이 `logging.getLogger(__name__)` 으로 로거를 만들지만 **아무도
설정을 하지 않았다.** 파이썬은 그런 경우 최후 수단 핸들러로 `WARNING` 이상만 stderr 에
내보낸다. 그래서 경고·예외는 새어 나오지만 `INFO` 는 통째로 버려진다.

우리 로그의 대부분이 INFO 다. 무엇이 잘 돌았는지, 어떤 판단을 했는지(예: "연결재무제표가
없어 별도재무제표로 조회한다")가 거기 있는데, 고장이 났을 때 볼 기록이 없다는 뜻이다.
화면의 가동 점검은 **지금 상태**만 알려주고 **무슨 일이 있었는지**는 알려주지 않는다.

## 설계

- `app` 로 시작하는 로거에만 손댄다. uvicorn·apscheduler·httpx 는 각자의 설정을 쓴다.
- 표준 출력으로 보낸다. systemd 가 그것을 journalctl 로 모으므로 파일을 따로 두지 않는다
  (서버 디스크가 45GB 이고 로그 회전은 systemd 가 이미 한다).
- **`propagate` 를 끈다.** 켜 두면 루트로도 올라가 같은 줄이 두 번 찍힌다.
- 두 번 불려도 핸들러가 겹치지 않게 한다. 테스트가 앱을 여러 번 만들기 때문이다.
  다시 부르면 **새 핸들러를 붙이는 대신 있던 것을 갱신한다** — 겹치면 모든 줄이 두 번
  찍히고, 건너뛰기만 하면 바뀐 설정이 반영되지 않는다.
"""

from __future__ import annotations

import logging
import sys

# 우리 코드의 로거는 전부 `app.` 으로 시작한다(`logging.getLogger(__name__)`).
APP_LOGGER = "app"

# 시각·수준·어느 모듈인지. journalctl 이 앞에 자기 시각을 붙이지만, 그것은 로그를 받은
# 시각이라 우리 시각도 함께 남긴다.
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"

_HANDLER_NAME = "app-stdout"


def configure_logging(level: int = logging.INFO, stream=None) -> None:
    """앱 로거를 표준 출력에 연결한다. 여러 번 불러도 안전하다.

    `stream` 은 테스트가 어디로 나갔는지 확인할 때만 쓴다. 비워 두면 표준 출력이다.

    **핸들러는 만들 때의 스트림을 붙잡는다.** 그래서 다시 부를 때 건너뛰면 바뀐
    스트림이 반영되지 않는다 — 있던 핸들러를 갱신하는 이유다.
    """
    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(level)

    target = stream if stream is not None else sys.stdout
    existing = next(
        (h for h in logger.handlers if getattr(h, "name", None) == _HANDLER_NAME), None
    )
    if existing is not None:
        existing.setStream(target)
        existing.setLevel(level)
    else:
        handler = logging.StreamHandler(target)
        handler.name = _HANDLER_NAME
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(handler)

    # 루트로 올려보내지 않는다 — 나중에 누군가 루트에 핸들러를 붙이면 같은 줄이 두 번
    # 찍힌다. 우리 로그는 우리 핸들러 하나로만 나간다.
    logger.propagate = False
