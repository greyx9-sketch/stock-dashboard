"""정기 작업 스케줄러.

지금 맡고 있는 일은 하나다: **KRX 확정 종가를 매일 자동으로 받아 오는 것.**

이 API 는 실시간이 아니다. 어떤 날의 확정 종가는 그다음 영업일 **오후 1시 이후**에 공개된다.
그래서 오후 1시가 조금 지난 시각에 한 번 돌린다.

서버가 24시간 떠 있다는 보장이 없다는 점이 설계의 핵심이다. 집 PC 는 꺼지고, VPS 도 재부팅된다.
꺼져 있던 동안의 날짜가 영영 비면 안 되므로:

- 서버가 뜰 때마다 **빠진 날을 찾아 채운다**(따라잡기).
- 정기 실행도 하루치가 아니라 최근 며칠을 훑는다. 이미 있는 날은 호출조차 하지 않으므로
  범위를 넉넉히 잡아도 비용이 늘지 않는다.

결과적으로 "정해진 시각에 한 번 돌기"가 아니라 "빠진 것을 계속 메우기"에 가깝다.
스케줄이 한 번 어긋나도 다음 실행이 알아서 복구한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.clients.krx import KrxError
from app.services import krx_ingest

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

JOB_ID = "krx-daily-close"

# 확정 종가는 오후 1시 이후 공개된다. 정각에 붙으면 아직 안 올라와 있을 수 있어 여유를 둔다.
RUN_HOUR = 13
RUN_MINUTE = 20

# 정기 실행이 훑는 범위(달력 일수). 연휴가 길어도 빠진 날이 남지 않도록 넉넉히 잡는다.
# 이미 저장된 날은 건너뛰므로 실제 호출 수는 새로 생긴 날에만 비례한다.
SCAN_DAYS = 14

# 서버가 뜨고 나서 따라잡기를 시작하기까지 기다리는 시간(초).
# 기동 직후에 무거운 작업을 걸면 첫 화면 응답이 느려진다.
STARTUP_DELAY_SEC = 20

# 오래 꺼져 있었을 수 있으므로 기동 시에는 더 넓게 훑는다.
STARTUP_SCAN_DAYS = 30


@dataclass
class RunReport:
    """마지막 실행이 무엇을 했는지. 화면에 그대로 보여준다."""

    started_at: datetime
    finished_at: datetime | None = None
    trading_days: int = 0
    rows: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.finished_at is not None


class KrxScheduler:
    """확정 종가 적재를 정해진 시각에 돌리는 스케줄러."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone=KST)
        self._last: RunReport | None = None
        self._running = False

    # ------------------------------------------------------------------ 수명 관리

    def start(self) -> None:
        # 영업일에만 돈다. 주말에 돌려 봐야 새로 올라온 데이터가 없다.
        # (공휴일은 굳이 거르지 않는다. 받아 보고 비면 휴장으로 처리되고, 호출 3건이면 끝난다.)
        self._scheduler.add_job(
            self.run,
            CronTrigger(day_of_week="mon-fri", hour=RUN_HOUR, minute=RUN_MINUTE, timezone=KST),
            id=JOB_ID,
            name="KRX 확정 종가 수집",
            kwargs={"scan_days": SCAN_DAYS},
            # 서버가 잠깐 멈췄다가 살아났을 때, 지나간 실행을 이 시간 안이면 따라잡는다.
            misfire_grace_time=3600,
            # 밀린 실행이 여러 번 쌓여도 한 번만 돈다. 어차피 하는 일이 같다.
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )

        # 기동 직후 따라잡기. 꺼져 있던 동안 빠진 날짜를 메운다.
        self._scheduler.add_job(
            self.run,
            "date",
            run_date=datetime.now(KST) + timedelta(seconds=STARTUP_DELAY_SEC),
            id=f"{JOB_ID}-catchup",
            name="KRX 확정 종가 따라잡기 (기동 시)",
            kwargs={"scan_days": STARTUP_SCAN_DAYS},
            max_instances=1,
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info("스케줄러 시작. 다음 정기 수집: %s", self.next_run_at)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------ 상태

    @property
    def next_run_at(self) -> datetime | None:
        job = self._scheduler.get_job(JOB_ID) if self._scheduler.running else None
        return job.next_run_time if job else None

    @property
    def last_run(self) -> RunReport | None:
        return self._last

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ 실제 작업

    async def run(self, scan_days: int = SCAN_DAYS) -> RunReport:
        """빠진 날짜의 확정 종가를 받아 저장한다.

        이미 저장된 날은 건너뛴다. 여러 번 돌아도 안전하다.
        """
        report = RunReport(started_at=datetime.now(KST))
        self._running = True
        try:
            result = await krx_ingest.ingest_recent(scan_days)
            report.trading_days = len(result.trading_days)
            report.rows = result.total_rows
            report.finished_at = datetime.now(KST)
            if report.rows:
                logger.info(
                    "확정 종가 수집 완료: %d 거래일 %d 행", report.trading_days, report.rows
                )
            else:
                logger.info("확정 종가 수집: 새로 받을 것 없음")
        except (KrxError, RuntimeError) as exc:
            # 인증키 문제나 포털 장애다. 다음 실행에서 다시 시도하면 되므로 서버를 죽이지 않는다.
            report.error = str(exc)
            report.finished_at = datetime.now(KST)
            logger.warning("확정 종가 수집 실패: %s", exc)
        except Exception as exc:  # 예상 못 한 오류로 스케줄러가 멈추면 안 된다.
            report.error = f"예상치 못한 오류: {exc}"
            report.finished_at = datetime.now(KST)
            logger.exception("확정 종가 수집 중 예상치 못한 오류")
        finally:
            self._running = False
            self._last = report

        return report


# 서버 전체가 공유하는 스케줄러 하나.
scheduler = KrxScheduler()
