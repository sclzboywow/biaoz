#!/bin/bash
set -euo pipefail

NAPCAT_DIR=/home/ubuntu/napcat
cd "$NAPCAT_DIR"

python3 - <<'PY'
import json
import re
from pathlib import Path

compose = Path("docker-compose.yml")
text = compose.read_text(encoding="utf-8")
text2 = re.sub(r"^\s*-\s*ACCOUNT=.*\n", "", text, flags=re.M)
if "ACCOUNT=" in text2:
    raise SystemExit("docker-compose still contains ACCOUNT=")
compose.write_text(text2, encoding="utf-8")
print("removed ACCOUNT from docker-compose.yml")

webui = Path("config/webui.json")
data = json.loads(webui.read_text(encoding="utf-8"))
if "autoLoginAccount" in data:
    del data["autoLoginAccount"]
webui.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
print("removed webui autoLoginAccount")
PY

docker compose up -d
sleep 6
echo "--- napcat login tail ---"
docker logs napcat --tail 12 2>&1 | grep -iE '快速登录|登录态|二维码|核心登录|5625523|2529213858|SD星辰' || docker logs napcat --tail 8 2>&1
curl -s http://127.0.0.1:8765/health || true
