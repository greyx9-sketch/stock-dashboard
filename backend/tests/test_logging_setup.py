"""앱 로그가 실제로 나가는지 확인한다.

**설정이 없으면 INFO 가 통째로 사라진다.** 파이썬 기본값은 최후 수단 핸들러로
WARNING 이상만 stderr 에 내보내기 때문이다. 실제로 그 상태로 배포돼 있었고
(2026-08-25 서버 점검에서 발견), "웹소켓 연결됨" 같은 줄이 하나도 남지 않았다.

고장 났을 때 볼 기록이 없다는 뜻이라 회귀로 못 박는다.
"""

from __future__ import annotations

import io
import logging

import pytest

from app.logging_setup import APP_LOGGER, configure_logging


@pytest.fixture
def out():
    """로그가 실제로 흘러나오는 곳. pytest 의 출력 가로채기에 기대지 않는다."""
    buffer = io.StringIO()
    configure_logging(stream=buffer)
    return buffer


def test_info_is_emitted(out):
    """**회귀 방지.** 우리 로그의 대부분이 INFO 다.

    설정이 없으면 파이썬이 WARNING 이상만 내보내 이 줄이 통째로 사라진다.
    """
    logging.getLogger("app.services.example").info("웹소켓 연결됨")
    assert "웹소켓 연결됨" in out.getvalue()


def test_warning_still_goes_out(out):
    logging.getLogger("app.clients.example").warning("토스 웹소켓 끊김")
    assert "토스 웹소켓 끊김" in out.getvalue()


def test_configuring_twice_does_not_double_the_output(out):
    """핸들러가 겹치면 모든 줄이 두 번 찍힌다."""
    configure_logging(stream=out)
    logging.getLogger("app.services.example").info("한 번만")
    assert out.getvalue().count("한 번만") == 1


def test_message_says_where_it_came_from(out):
    """어느 모듈에서 났는지 없으면 로그를 따라갈 수 없다."""
    logging.getLogger("app.services.universe").info("적재 완료")
    assert "app.services.universe" in out.getvalue()


def test_other_libraries_are_left_alone(out):
    """uvicorn·apscheduler 는 각자의 설정을 쓴다. 우리가 건드리면 엉뚱한 곳이 바뀐다."""
    assert not logging.getLogger("uvicorn").handlers
    # 우리 로그는 우리 핸들러 하나로만 나간다.
    assert logging.getLogger(APP_LOGGER).propagate is False


# ---------------------------------------------------------------- 키가 새지 않게


def test_request_loggers_are_kept_quiet(out):
    """**OpenDART 는 인증키를 쿼리 문자열로 받는다.**

    httpx 가 INFO 에서 요청 URL 을 통째로 찍으므로, 그 로거가 열리면 키가 journalctl 에
    평문으로 쌓인다. 실제로 확인했다(2026-08-25, 임시로 모든 로그를 켜고 돌렸을 때).

    지금은 우리가 `app` 만 설정해 조용하지만, 나중에 누가 `logging.basicConfig()` 를
    부르면 그 순간 새기 시작한다. 그래서 명시적으로 눌러 둔다.
    """
    from app.logging_setup import NOISY_LOGGERS

    for name in NOISY_LOGGERS:
        assert logging.getLogger(name).level >= logging.WARNING, f"{name} 로거가 열려 있다"


def test_request_loggers_stay_quiet_even_after_basic_config(out):
    """루트를 열어도 요청 URL 은 나가지 않아야 한다."""
    from app.logging_setup import NOISY_LOGGERS, configure_logging

    logging.basicConfig(level=logging.INFO)
    configure_logging(stream=out)

    logging.getLogger("httpx").info("GET https://opendart.fss.or.kr/api/list.json?crtfc_key=비밀")
    assert "crtfc_key" not in out.getvalue()
    assert all(logging.getLogger(n).level >= logging.WARNING for n in NOISY_LOGGERS)
