#!/usr/bin/env bash
# 서버에서 최신 코드로 갱신하는 스크립트.
#
# 배포를 마친 뒤 코드가 바뀔 때마다 서버에서 이것만 실행하면 된다.
#   cd /opt/stock && ./deploy/update.sh
#
# 하는 일: 코드 받기 → 파이썬 패키지 갱신 → 화면 빌드 → 서비스 재시작 → 살아 있는지 확인

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "== 1/5 코드 받기"
git pull --ff-only

echo "== 2/5 파이썬 패키지"
"$ROOT/.venv/bin/pip" install -q -r backend/requirements.txt

echo "== 3/5 화면 빌드"
cd "$ROOT/frontend"
# npm ci 는 package-lock.json 그대로 설치한다. 서버에서 버전이 제멋대로 올라가지 않게 한다.
npm ci --silent
npm run build
cd "$ROOT"

echo "== 4/5 서비스 재시작"
sudo systemctl restart stock-dashboard

echo "== 5/5 확인"
# 뜨는 데 몇 초 걸린다. 될 때까지 잠깐 기다린다.
for i in $(seq 1 20); do
	if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
		echo "정상: $(curl -fsS http://127.0.0.1:8000/health)"
		exit 0
	fi
	sleep 1
done

echo "서버가 응답하지 않는다. 아래로 원인을 확인한다:"
echo "  sudo journalctl -u stock-dashboard -n 50 --no-pager"
exit 1
