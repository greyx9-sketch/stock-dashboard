"""알림 메시지 구성 테스트.

메시지 한 통만 보고 **무엇이 어떻게 고장났는지** 알 수 있어야 한다. "오류 발생" 한 줄만
오는 알림은 결국 서버에 들어가 봐야 하므로 없는 것과 큰 차이가 없다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from watchdog import _body, compose  # noqa: E402


PAYLOAD = {
    "status": "degraded",
    "summary": "현재가: 장중인데 12분째 갱신이 없습니다.",
    "checks": [
        {"name": "DB", "status": "ok", "detail": "정상"},
        {"name": "현재가", "status": "degraded", "detail": "장중인데 12분째 갱신이 없습니다."},
    ],
    "recent_errors": [{"at": "2026-08-20T01:00:00+00:00", "path": "/api/prices", "status": 500, "detail": ""}],
}


def test_message_names_the_broken_part():
    text = compose("degraded", PAYLOAD["summary"], PAYLOAD)
    assert "현재가" in text
    assert "12분째" in text


def test_message_skips_healthy_checks():
    """정상 항목까지 나열하면 문제가 묻힌다."""
    text = compose("degraded", PAYLOAD["summary"], PAYLOAD)
    assert "DB" not in text


def test_message_includes_site_url():
    """알림을 받고 바로 확인하러 갈 수 있어야 한다."""
    assert "129.225.188.89" in compose("down", "앱이 응답하지 않습니다", None)


def test_message_works_without_payload():
    """앱이 죽으면 상세 응답 자체가 없다. 그때도 메시지는 만들어져야 한다."""
    text = compose("down", "앱이 응답하지 않습니다", None)
    assert "앱이 응답하지 않습니다" in text
    assert "DOWN" in text


def test_discord_and_slack_use_different_body_keys():
    """본문 키를 틀리면 웹훅이 400 을 내고 알림이 조용히 사라진다."""
    discord = json.loads(_body("https://discord.com/api/webhooks/1/abc", "안녕"))
    slack = json.loads(_body("https://hooks.slack.com/services/T/B/x", "안녕"))
    assert discord == {"content": "안녕"}
    assert slack == {"text": "안녕"}


def test_unknown_host_falls_back_to_text():
    assert json.loads(_body("https://example.com/hook", "안녕")) == {"text": "안녕"}
