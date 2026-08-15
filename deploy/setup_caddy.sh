#!/usr/bin/env bash
# Caddyfile 에 basic_auth 해시를 넣고 Caddy 를 띄운다.
# .env 의 SITE_PASSWORD 를 서버 안에서만 읽어 해시로 바꾸므로 평문이 밖으로 나가지 않는다.
set -euo pipefail

PW=$(sudo grep '^SITE_PASSWORD=' /opt/stock/.env | cut -d= -f2- | tr -d '\r')
if [ -z "$PW" ]; then
	echo "ERROR: SITE_PASSWORD 가 비어 있다" >&2
	exit 1
fi

HASH=$(caddy hash-password --plaintext "$PW")
echo "해시 생성됨 (길이 ${#HASH})"

# 로그 폴더 — Caddy 는 caddy 사용자로 돌아서 미리 만들어 주지 않으면 기동에 실패한다.
sudo mkdir -p /var/log/caddy
sudo chown -R caddy:caddy /var/log/caddy
sudo chmod 755 /var/log/caddy

sudo cp /opt/stock/deploy/Caddyfile /etc/caddy/Caddyfile

# 자리표시자 한 곳만 바꾼다. 주석 블록의 예시는 그대로 둔다.
sudo HASH="$HASH" python3 <<'PYEOF'
import io, os, re

path = "/etc/caddy/Caddyfile"
src = io.open(path, encoding="utf-8").read()
hash_value = os.environ["HASH"]

# 활성 블록의 `view <자리표시자>` 한 줄만 교체한다(주석 줄은 건너뛴다).
out = []
done = False
for line in src.splitlines(keepends=True):
    if not done and line.lstrip().startswith("view ") and "2a$14$" in line:
        indent = line[: len(line) - len(line.lstrip())]
        out.append(f"{indent}view {hash_value}\n")
        done = True
    else:
        out.append(line)

if not done:
    raise SystemExit("자리표시자를 찾지 못했다")

with io.open(path, "w", encoding="utf-8") as f:
    f.write("".join(out))
print("Caddyfile 치환 완료")
PYEOF

echo "--- 검증: 활성 view 줄 ---"
sudo python3 <<'PYEOF'
import io
for i, line in enumerate(io.open("/etc/caddy/Caddyfile", encoding="utf-8"), 1):
    t = line.strip()
    if t.startswith("view "):
        token = t.split()[-1]
        ascii_only = all(ord(c) < 128 for c in token)
        print(f"  line {i}: 길이 {len(token)}, 순수 ASCII(=해시) {ascii_only}, 앞 10자 {token[:10]}")
PYEOF

sudo caddy validate --config /etc/caddy/Caddyfile 2>&1 | tail -1
sudo systemctl restart caddy
sleep 4
echo "caddy: $(systemctl is-active caddy)"
