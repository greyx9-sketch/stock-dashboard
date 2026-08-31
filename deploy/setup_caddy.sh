#!/usr/bin/env bash
# Caddyfile 에 접근 아이디와 비밀번호 해시를 넣고 Caddy 를 띄운다.
#
# 아이디·비밀번호는 .env 의 SITE_USER·SITE_PASSWORD 하나만 고치면 된다. Caddyfile 은
# 자리표시자만 들고 있고 손대지 않는다.
#
# 비밀번호 평문은 서버 밖으로 나가지 않는다 — 여기서 읽어 해시로 바꾼 것만 파일에 들어간다.
# 아이디도 화면에 찍지 않는다. 대화 기록이나 로그에 남기지 않기 위해서다.
#
# 고친 뒤 실행:  bash /opt/stock/deploy/setup_caddy.sh
set -euo pipefail

ENV_FILE=/opt/stock/.env

read_env() {
	# 값에 = 가 들어 있어도 첫 = 뒤 전부를 값으로 본다. 윈도우에서 편집했을 때 붙는 \r 을 뗀다.
	sudo grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r'
}

USER_NAME=$(read_env SITE_USER)
# 예전 .env 에는 SITE_USER 줄이 없다. 그때까지 쓰던 값을 기본으로 둬야 갑자기 못 들어가는 일이 없다.
USER_NAME=${USER_NAME:-view}

PW=$(read_env SITE_PASSWORD)
if [ -z "$PW" ]; then
	echo "ERROR: .env 의 SITE_PASSWORD 가 비어 있다" >&2
	exit 1
fi

# 아이디에 공백이 섞이면 Caddyfile 문법이 깨져 Caddy 가 아예 안 뜬다. 미리 막는다.
case "$USER_NAME" in
*[[:space:]]* | *'{'* | *'}'*)
	echo "ERROR: SITE_USER 에 공백이나 중괄호를 쓸 수 없다" >&2
	exit 1
	;;
esac

HASH=$(caddy hash-password --plaintext "$PW")
unset PW
echo "아이디 ${#USER_NAME}자 · 해시 ${#HASH}자 생성됨"

# 로그 폴더 — Caddy 는 caddy 사용자로 돌아서 미리 만들어 주지 않으면 기동에 실패한다.
sudo mkdir -p /var/log/caddy
sudo chown -R caddy:caddy /var/log/caddy
sudo chmod 755 /var/log/caddy

sudo cp /opt/stock/deploy/Caddyfile /etc/caddy/Caddyfile

# 활성 블록의 자리표시자 한 줄만 바꾼다. 주석 블록(HTTPS 예시)은 그대로 둬야
# 나중에 도메인을 붙일 때 다시 쓸 수 있고, 해시가 주석에 남지도 않는다.
sudo USER_NAME="$USER_NAME" HASH="$HASH" python3 <<'PYEOF'
import io, os

path = "/etc/caddy/Caddyfile"
src = io.open(path, encoding="utf-8").read()
user = os.environ["USER_NAME"]
hash_value = os.environ["HASH"]

out, done = [], False
for line in src.splitlines(keepends=True):
    stripped = line.lstrip()
    # 주석(#)으로 시작하는 줄은 건너뛴다 — 활성 블록 한 곳만 채운다.
    if not done and not stripped.startswith("#") and "__SITE_USER__" in line:
        indent = line[: len(line) - len(stripped)]
        out.append(f"{indent}{user} {hash_value}\n")
        done = True
    else:
        out.append(line)

if not done:
    raise SystemExit(
        "자리표시자 __SITE_USER__ 를 찾지 못했다. deploy/Caddyfile 이 옛 버전인지 확인한다."
    )

with io.open(path, "w", encoding="utf-8") as f:
    f.write("".join(out))
print("Caddyfile 치환 완료")
PYEOF

echo "--- 검증: 활성 basic_auth 줄 (값은 숨김) ---"
sudo python3 <<'PYEOF'
import io

for i, line in enumerate(io.open("/etc/caddy/Caddyfile", encoding="utf-8"), 1):
    t = line.strip()
    if t.startswith("#") or "$2a$" not in t:
        continue
    parts = t.split()
    if len(parts) != 2:
        continue
    name, token = parts
    ok = token.startswith("$2a$14$") and all(ord(c) < 128 for c in token)
    print(f"  line {i}: 아이디 {len(name)}자 · 해시 형식 정상 {ok} · 해시 {len(token)}자")
PYEOF

if grep -q "__SITE_USER__\|__PASSWORD_HASH__" <(sudo grep -v '^\s*#' /etc/caddy/Caddyfile); then
	echo "ERROR: 활성 블록에 자리표시자가 남아 있다" >&2
	exit 1
fi

sudo caddy validate --config /etc/caddy/Caddyfile 2>&1 | tail -1
sudo systemctl restart caddy
sleep 4
echo "caddy: $(systemctl is-active caddy)"

# 선이 제대로 그어졌는지 양쪽에서 확인한다. 자리표시자가 남거나 매처 문법이 깨지면
# 여기서 잡힌다. **둘 다 봐야 한다** — 한쪽만 보면 "전부 열림"이나 "전부 잠김"을 놓친다.
read_code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/ || true)
echo "비밀번호 없이 보기: HTTP $read_code (200 이어야 정상)"
[ "$read_code" = "200" ] || {
	echo "ERROR: 누구나 볼 수 있어야 하는데 막혔다" >&2
	exit 1
}

# 쓰기는 막혀야 한다. 인증이 통과하면 본문이 없어 422 가 되므로, 401 이 아니면 잘못된 것이다.
write_code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1/api/watchlist || true)
echo "비밀번호 없이 쓰기: HTTP $write_code (401 이어야 정상)"
[ "$write_code" = "401" ] || {
	echo "ERROR: 쓰기에 비밀번호가 걸리지 않았다 — 남이 메모를 지우거나 분석을 돌릴 수 있다" >&2
	exit 1
}
