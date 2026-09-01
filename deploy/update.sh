#!/usr/bin/env bash
# 서버에서 최신 코드로 갱신하는 스크립트.
#
# **ubuntu 계정으로 실행한다.** 코드를 만지는 일은 이 스크립트가 stock 계정으로 알아서
# 넘긴다:
#   cd /opt/stock && ./deploy/update.sh
#
# 전에는 `sudo -u stock -H bash -c 'cd /opt/stock && ./deploy/update.sh'` 로 안내했는데,
# 그러면 4단계 `sudo systemctl restart` 에서 멈춘다 — stock 계정에는 sudo 비밀번호가
# 없기 때문이다(서비스 계정이라 있는 것이 오히려 이상하다). 파일 작업은 stock 으로,
# 서비스 재시작은 ubuntu 로 나누는 것이 맞다.
#
# 하는 일: 코드 받기 → 파이썬 패키지 갱신 → 화면 빌드 → 서비스 재시작 → 살아 있는지 확인

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# 파일을 건드리는 단계는 stock 으로 돌린다. root 로 하면 소유자가 바뀌어 다음 배포가 깨진다.
# 이미 stock 으로 실행 중이면 그대로 돈다.
as_stock() {
	if [ "$(id -un)" = "stock" ]; then
		bash -c "$1"
	else
		sudo -u stock -H bash -c "$1"
	fi
}

echo "== 1/5 코드 받기"
as_stock "cd '$ROOT' && git pull --ff-only"

echo "== 2/5 파이썬 패키지"
as_stock "'$ROOT/.venv/bin/pip' install -q -r '$ROOT/backend/requirements.txt'"

echo "== 3/5 화면 빌드"
# npm ci 는 package-lock.json 그대로 설치한다. 서버에서 버전이 제멋대로 올라가지 않게 한다.
as_stock "cd '$ROOT/frontend' && npm ci --silent && npm run build"

echo "== 4/5 서비스 재시작"
if ! sudo -n true 2>/dev/null; then
	cat <<-MSG
		비밀번호 없이 sudo 를 쓸 수 없어 재시작하지 못했다.
		여기까지(코드·패키지·화면)는 반영됐다. ubuntu 계정으로 아래를 실행하면 끝난다:
		  sudo systemctl restart stock-dashboard
	MSG
	exit 1
fi
# 서비스 파일이 바뀐 채로 재시작하면 systemd 가 옛 정의를 그대로 쓴다.
sudo systemctl daemon-reload
sudo systemctl restart stock-dashboard

echo "== 5/5 확인"
# 뜨는 데 몇십 초 걸린다 — DB 스키마 맞추기와 토스 웹소켓 연결이 먼저다.
# 20초로 뒀다가 29초 걸린 배포에서 "서버가 응답하지 않는다"는 헛경보를 봤다.
for i in $(seq 1 60); do
	if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
		echo "정상: $(curl -fsS http://127.0.0.1:8000/health)"
		exit 0
	fi
	sleep 1
done

echo "서버가 응답하지 않는다. 아래로 원인을 확인한다:"
echo "  sudo journalctl -u stock-dashboard -n 50 --no-pager"
exit 1
