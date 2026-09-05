"""오늘이 언제인가 — 시간대 경계.

`docs/외부저장소조사.md` B-5. **개발 PC 는 KST, 배포 서버는 UTC 다.** 날짜 경계 처리가
기계마다 다르면 "어제 공시"가 서버와 집에서 다르게 나온다.

실제로 어긋나 있었다(2026-09-06 확인). 서버 `date` 는 `Sat Sep 5 16:52 UTC`,
같은 순간 한국은 `9월 6일 일요일 01:52`. 한국시간 자정~아침 9시 사이에는 **서버의
"오늘"이 사용자의 어제**였다.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone

from app.clock import KST, today_kst


def test_kst_is_nine_hours_ahead_of_utc():
    """서머타임이 없어 고정 오프셋으로 정확하다."""
    moment = datetime(2026, 9, 5, 16, 52, tzinfo=timezone.utc)
    assert moment.astimezone(KST).date() == date(2026, 9, 6)


def test_today_is_korean_today_even_on_a_utc_machine(monkeypatch):
    """**회귀(2026-09-06).** 기계가 UTC 여도 오늘은 한국 달력의 오늘이다.

    배포 서버에서 실제로 벌어진 상황을 그대로 만든다 — UTC 로 9월 5일 16:52 인 순간,
    한국은 이미 9월 6일이다. `date.today()` 는 여기서 9월 5일을 내놓았고, 그래서
    다가오는 일정의 D-n 이 하루씩 밀리고 아침에 올라온 공시가 조회 창 밖으로 나갔다.
    """
    utc_moment = datetime(2026, 9, 5, 16, 52, tzinfo=timezone.utc)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_moment.astimezone(tz) if tz else utc_moment.replace(tzinfo=None)

    monkeypatch.setattr("app.clock.datetime", _FrozenDatetime)

    assert today_kst() == date(2026, 9, 6)
    # 기계 시간대를 따랐다면 이 값이 나왔을 것이다. 그것과 다르다는 것이 이 테스트의 요지다.
    assert utc_moment.date() == date(2026, 9, 5)


def test_no_module_computes_today_from_the_host_clock():
    """**`date.today()` 를 다시 쓰지 못하게 못 박는다.**

    이 프로젝트가 다루는 날짜 — 거래일, 공시일, 보고서 기간 — 는 전부 한국 기준이거나
    시장이 스스로 날짜를 붙여 보내 준다. 기계의 시간대가 끼어들 자리가 없다.
    앞으로 누군가 `date.today()` 를 넣으면 여기서 걸린다.
    """
    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app")
    offenders = []
    for folder, _, files in os.walk(root):
        for name in files:
            if not name.endswith(".py") or name == "clock.py":
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if "date.today()" not in line:
                        continue
                    # 설명글에서 언급하는 것은 봐준다 — 이 저장소는 코드 이름을
                    # 역따옴표로 감싸 쓴다(주석·독스트링 모두).
                    if "`date.today()`" in line or line.lstrip().startswith("#"):
                        continue
                    offenders.append(f"{path}:{lineno}")
    assert not offenders, (
        "기계 시간대로 오늘을 구하는 곳이 있습니다. `app.clock.today_kst()` 를 쓰세요:\n  "
        + "\n  ".join(offenders)
    )
