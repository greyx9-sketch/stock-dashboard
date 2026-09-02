"""미국 스크리너 유니버스를 한 번에 채운다.

야간 스케줄러(`services/scheduler._load_us_universe`)와 하는 일이 같지만, 그쪽은
하룻밤에 `US_LOAD_PER_RUN` 개씩만 받는다. 회사 하나의 재무가 3~4MB 라 300개를
한꺼번에 받으면 1GB 에 가깝기 때문이다. 처음 채울 때는 며칠을 기다리는 대신
이 스크립트로 한 번에 돌린다.

    python scripts/backfill_us_universe.py [--target 300] [--limit 400]

여러 번 돌려도 안전하다. 이미 받아 둔 회사는 건너뛰므로, 중간에 끊기면 다시
돌리면 이어서 받는다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.base import init_db  # noqa: E402
from app.services import us_universe  # noqa: E402
from app.services.scheduler import _last_full_year  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=us_universe.SCREEN_TARGET,
                        help="매출 상위 몇 개를 후보로 삼을지")
    parser.add_argument("--limit", type=int, default=None,
                        help="이번 실행에서 새로 받을 회사 수 상한. 없으면 전부")
    parser.add_argument("--period", default=None, help="예: CY2025")
    args = parser.parse_args()

    # 이 스크립트는 앱을 거치지 않는다. 새로 늘어난 컬럼(last_close 등)이 붙어 있지
    # 않은 DB 에 쓰면 'no such column' 이 난다 — 서버가 하는 준비를 여기서도 한다.
    init_db()

    period = args.period or _last_full_year()
    started = time.monotonic()

    logger.info("후보를 고른다 — %s 매출 상위 %d개", period, args.target)
    tickers = await us_universe.candidates(period, target=args.target)
    logger.info("후보 %d개", len(tickers))
    if not tickers:
        logger.error("후보가 없다. 횡단면을 받지 못했거나 티커 매핑이 비었다.")
        return 1

    todo = us_universe.not_loaded(tickers)
    logger.info("그중 아직 안 받은 곳 %d개 (이미 받아 둔 곳 %d개)",
                len(todo), len(tickers) - len(todo))
    if args.limit is not None:
        todo = todo[: args.limit]
        logger.info("이번 실행에서는 %d개만 받는다", len(todo))

    if todo:
        report = await us_universe.load(todo)
        logger.info("재무 적재 — 요청 %s · 저장 %s", report.requested, report.financials_saved)

    # 대표 티커를 고르는 기준에 "주가를 매길 수 있는가"가 들어가므로, 형제 티커까지
    # 받아 둔 뒤에 유니버스를 센다. 순서를 바꾸면 첫 실행에서 대표가 엉뚱해진다.
    wanted = us_universe.pricing_tickers()
    logger.info("시세·주식수를 받을 티커 %d개 (형제 포함)", len(wanted))
    saved = await us_universe.refresh_closes(wanted)
    logger.info("주가 저장 %d개", saved)
    listed = await us_universe.refresh_listed_shares(wanted)
    logger.info("상장주식수 저장 %d개", listed)

    universe = us_universe.screen_universe()
    logger.info("끝. %.1f초 걸렸다. 유니버스 %d개", time.monotonic() - started, len(universe))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
