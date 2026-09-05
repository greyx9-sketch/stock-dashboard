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
from apscheduler.triggers.interval import IntervalTrigger

from app.clients.dart import DartError
from app.clients.krx import KrxError
from app.clients.sec import SecError
from app.services import dart_corps, krx_ingest, sec_companies
from app.clock import KST

logger = logging.getLogger(__name__)

# 한국 표준시는 `app.clock` 한 곳에서만 정의한다. 여기서 다시 만들면
# 나중에 한쪽만 고쳐지는 종류의 버그가 생긴다.

JOB_ID = "krx-daily-close"

# 유니버스 적재 시각(KST). **확정 종가 수집(13:20) 이 끝난 뒤**여야 시가총액 상위가
# 최신 자료로 뽑힌다. 40분이면 그 수집이 끝나고도 남는다.
UNIVERSE_JOB_ID = "screener-universe"
UNIVERSE_HOUR = 14
UNIVERSE_MINUTE = 0

# 하룻밤에 새로 받을 미국 회사 수의 상한. 회사당 3~4MB 라 이 정도가 한 번에
# 내려받아도 부담이 없는 양이다. 이미 받아 둔 회사는 세지 않으므로, 목표
# (`us_universe.SCREEN_TARGET`)에 닿으면 이 일은 저절로 값이 싸진다.
US_LOAD_PER_RUN = 80

# 새 연차보고서 자동 분석 시각(KST). **돈이 나가는 유일한 예약 작업이다.**
#
# 이른 아침에 둔다 — 사용자가 낮에 직접 분석을 누를 때 하루 상한이 이미 차 있으면
# 안 되는데, 자동 분석은 사람 몫 5건을 늘 남기므로(`services/auto_analysis.py`)
# 먼저 돌아도 막지 않는다. 새 보고서가 없으면 아무 일도 하지 않는다.
AUTO_ANALYSIS_JOB_ID = "auto-analysis"
AUTO_ANALYSIS_HOUR = 7
AUTO_ANALYSIS_MINUTE = 30

# 자동 분석은 결과를 기다리지 않고 배치로 맡기고 끝난다(반값). 그 결과를 주워 오는 주기.
#
# 배치는 보통 한 시간 안에 끝나고 최대 24시간이다. 20분마다 보면 대개 첫 시간 안에
# 거두고, 늦어도 하루 안에는 들어온다. 대기 중인 배치가 없으면 DB 만 보고 끝나므로
# 헛돈도 헛수고도 없다.
BATCH_COLLECT_JOB_ID = "analysis-batch-collect"
BATCH_COLLECT_MINUTES = 20

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


def _last_full_year() -> str:
    """SEC 횡단면에 물어볼 구간. 지난 회계연도를 쓴다.

    올해 것은 아직 다 제출되지 않아 회사가 몇 안 된다. 한 해 뒤로 물러서면
    대부분의 10-K 가 들어와 있다.
    """
    return f"CY{datetime.now(KST).year - 1}"


@dataclass
class RunReport:
    """마지막 실행이 무엇을 했는지. 화면에 그대로 보여준다."""

    started_at: datetime
    finished_at: datetime | None = None
    trading_days: int = 0
    rows: int = 0
    error: str | None = None
    corp_rows: int = 0  # 함께 갱신한 DART 고유번호 매핑 건수

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

        # 스크리너·동종업계 비교가 볼 유니버스를 채운다. **확정 종가 수집보다 뒤에** 둔다 —
        # 시가총액 상위를 그 자료에서 고르기 때문이다.
        #
        # 조건에 맞는 종목을 찾으려면 후보 전부의 지표를 미리 알아야 해서, 조회 시점이
        # 아니라 여기서 받아 둔다(`services/universe.py` 참고). 300종목에 5분쯤 걸리고
        # 이미 받아 둔 것은 건너뛰므로 평소에는 훨씬 빠르다.
        self._scheduler.add_job(
            self._load_universe,
            CronTrigger(day_of_week="mon-fri", hour=UNIVERSE_HOUR, minute=UNIVERSE_MINUTE,
                        timezone=KST),
            id=UNIVERSE_JOB_ID,
            name="스크리너 유니버스 적재",
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )

        # 관심종목에 새 연차보고서가 올라왔는지 보고, 있으면 분석한다.
        # **평일만 돈다** — 보고서는 영업일에 제출되고, 주말에 훑어 봐야 새 것이 없다.
        self._scheduler.add_job(
            self._auto_analysis,
            CronTrigger(day_of_week="mon-fri", hour=AUTO_ANALYSIS_HOUR,
                        minute=AUTO_ANALYSIS_MINUTE, timezone=KST),
            id=AUTO_ANALYSIS_JOB_ID,
            name="새 연차보고서 자동 분석",
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )

        # 배치로 맡긴 분석 결과를 주워 온다. 맡긴 것이 없으면 아무 일도 하지 않는다.
        # 보고서는 주말에 안 나오지만 **제출한 배치는 주말을 넘어 끝날 수 있으므로**
        # 이쪽은 날짜를 가리지 않고 돌린다.
        self._scheduler.add_job(
            self._collect_batches,
            IntervalTrigger(minutes=BATCH_COLLECT_MINUTES),
            id=BATCH_COLLECT_JOB_ID,
            name="분석 배치 결과 수거",
            misfire_grace_time=600,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info("스케줄러 시작. 다음 정기 수집: %s", self.next_run_at)

    async def _auto_analysis(self) -> None:
        """새 연차보고서 자동 분석. **실패해도 서버를 흔들지 않는다.**"""
        from app.services import auto_analysis

        try:
            await auto_analysis.run()
        except Exception:
            logger.exception("자동 분석 실패 — 다음 주기에 다시 시도한다")

    async def _collect_batches(self) -> None:
        """맡긴 분석 결과 수거. **실패해도 서버를 흔들지 않는다.**

        수거를 몷 해도 대기 행은 그대로 남아 다음 주기에 다시 둔다. 결과는 29일간
        보관되므로 몇 번 놓쳐도 잃지 않는다.
        """
        from app.services import auto_analysis

        try:
            await auto_analysis.collect_pending()
        except Exception:
            logger.exception("배치 결과 수거 실패 — 다음 주기에 다시 시도한다")

    async def _load_universe(self) -> None:
        """유니버스 적재. **실패해도 서버를 흔들지 않는다** — 스크리너가 어제 자료로
        도는 것은 사이트가 멈추는 것과 다르다.

        국내와 미국을 이어서 채운다. 미국이 실패해도 국내는 이미 끝나 있다.
        """
        from app.services import universe

        try:
            await universe.load()
        except Exception:
            logger.exception("국내 유니버스 적재 실패 — 다음 주기에 다시 시도한다")

        try:
            await self._load_us_universe()
        except Exception:
            logger.exception("미국 유니버스 적재 실패 — 다음 주기에 다시 시도한다")

    async def _load_us_universe(self) -> None:
        """미국 동종업계 비교와 스크리너가 볼 종목들.

        후보를 두 곳에서 모은다.

        **거래대금 상위**(토스) — 사용자가 실제로 화면에서 보는 종목이다. 다만 이
        랭킹은 상위 100종목까지만 덮는다. 유니버스가 오래 작았던 원인이 여기였다.

        **매출 상위**(SEC 횡단면) — 그 벽이 없다. 한 번의 호출로 수천 회사의 매출이
        오므로 거기서 매출 큰 순으로 자른다(`us_universe.candidates`).

        거래대금 쪽을 앞에 둔다. 둘 다 못 받을 때 먼저 채워야 하는 것은 사용자가
        지금 보고 있는 종목이기 때문이다.

        **한 번에 다 받지 않는다.** 회사 하나의 재무가 3~4MB 라 300개를 한꺼번에
        받으면 1GB 에 가깝다. 이미 받아 둔 회사는 `load` 가 건너뛰므로, 밤마다
        조금씩 받아 며칠에 걸쳐 채운다.
        """
        from app.routers.us_stocks import top_us_symbols
        from app.services import us_universe

        wanted: list[str] = []
        try:
            wanted.extend(await top_us_symbols(us_universe.DEFAULT_SIZE))
        except Exception:
            logger.warning("거래대금 상위를 받지 못했다", exc_info=True)

        try:
            wanted.extend(await us_universe.candidates(_last_full_year()))
        except Exception:
            logger.warning("매출 횡단면을 받지 못했다", exc_info=True)

        # 두 출처가 겹친다. 앞선 것을 남기고 순서를 지킨다.
        seen: set[str] = set()
        tickers = [t for t in wanted if not (t in seen or seen.add(t))]
        if not tickers:
            return

        # **아직 안 받은 것 중에서** 자른다. 후보 앞에서 그냥 자르면 앞쪽이 다 찬
        # 뒤로는 매번 같은 것을 다시 훑고 뒤쪽은 차례가 오지 않는다.
        todo = us_universe.not_loaded(tickers)[:US_LOAD_PER_RUN]
        if todo:
            await us_universe.load(todo)

        # 시세는 값이 싸다(200종목 한 묶음). 재무를 받아 둔 종목 전부를 매번 갱신한다 —
        # 스크리너가 이 값으로 시가총액을 내므로 하루만 묵어도 PER 이 어제 것이 된다.
        # 대표만이 아니라 형제 티커까지 받는다 — "주가를 매길 수 있는가"가 대표를
        # 고르는 기준이라, 형제 값이 없으면 그 판단을 못 한다.
        pricing = us_universe.pricing_tickers()
        await us_universe.refresh_closes(pricing)
        # 티커별 상장주식수. 대표 티커를 가리는 데 쓴다 — 자주 바뀌지 않지만
        # 새로 담긴 회사의 형제 티커는 값이 없으므로 같이 돌린다.
        await us_universe.refresh_listed_shares(pricing)

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
            # DART 고유번호 매핑을 먼저 본다. 오래됐을 때만 실제로 받는다(주 1회).
            # 여기서 실패해도 확정 종가 수집은 계속해야 하므로 따로 감싼다.
            try:
                corp = await dart_corps.sync_corp_codes()
                report.corp_rows = 0 if corp.skipped else corp.rows
            except (DartError, RuntimeError) as exc:
                logger.warning("DART 고유번호 매핑 갱신 실패(계속 진행): %s", exc)

            # SEC 티커 매핑도 같은 방식으로 본다. 여기서 실패해도 나머지는 계속한다 —
            # 세 개는 서로 다른 데이터 소스라 하나가 죽었다고 다른 둘을 멈출 이유가 없다.
            try:
                await sec_companies.sync_companies()
            except (SecError, RuntimeError) as exc:
                logger.warning("SEC 티커 매핑 갱신 실패(계속 진행): %s", exc)

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
