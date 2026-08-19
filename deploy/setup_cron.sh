#!/usr/bin/env bash
# 서버의 정기 작업(cron)을 등록한다. **ubuntu 계정으로 실행한다.**
#
#   bash /opt/stock/deploy/setup_cron.sh
#
# 두 가지를 건다. 둘 다 `stock` 계정의 crontab 에 들어간다 — 파일을 만드는 작업이라
# 소유자가 stock 이어야 다음 배포가 깨지지 않는다.
#
#   1. DB 백업        매일 21:20 UTC = 06:20 KST
#   2. 가동 감시       10분마다
#
# **서버 시간은 UTC 다.** 03:40 으로 적으면 한국 시간 12:40 — 장중이다. 실제로 한 번
# 그렇게 걸었다가 옮겼다. 시각을 고칠 때는 반드시 UTC 로 환산해서 적는다.
#
# 여러 번 돌려도 안전하다. 같은 표시가 붙은 줄을 지우고 다시 넣는다.

set -euo pipefail

ROOT=/opt/stock
MARK="# stock-dashboard"

if [ "$(id -un)" = "stock" ]; then
	run_as_stock() { bash -c "$1"; }
else
	run_as_stock() { sudo -u stock -H bash -c "$1"; }
fi

# 기존 crontab 에서 이 스크립트가 넣은 줄만 걷어낸다. 사람이 손으로 넣은 줄은 남긴다.
current="$(run_as_stock 'crontab -l 2>/dev/null' | grep -v "$MARK" || true)"

read -r -d '' lines <<CRON || true
$current
20 21 * * * cd $ROOT && ./.venv/bin/python backend/scripts/backup_db.py >> /tmp/backup.log 2>&1 $MARK
*/10 * * * * cd $ROOT && ./.venv/bin/python backend/scripts/watchdog.py >> /tmp/watchdog.log 2>&1 $MARK
CRON

# 빈 줄을 걷어내고 넣는다. 앞에 빈 줄이 있으면 crontab 이 통째로 거부하는 경우가 있다.
printf '%s\n' "$lines" | grep -v '^[[:space:]]*$' | run_as_stock 'crontab -'

echo "== 등록된 정기 작업"
run_as_stock 'crontab -l'

echo
echo "== 감시 스크립트 시험 실행"
run_as_stock "cd $ROOT && ./.venv/bin/python backend/scripts/watchdog.py"

echo
echo "알림을 실제로 받으려면 .env 의 ALERT_WEBHOOK_URL 에 디스코드·슬랙 웹훅 주소를 넣고"
echo "  cd $ROOT && ./.venv/bin/python backend/scripts/watchdog.py --test"
echo "로 연결을 확인하면 된다. 비어 있어도 감시는 돌고 알림만 건너뛴다."
