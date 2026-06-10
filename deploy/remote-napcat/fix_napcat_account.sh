#!/bin/bash
set -euo pipefail

NAPCAT_DIR=/home/ubuntu/napcat
ACCOUNT=5625523

cd "$NAPCAT_DIR"

# docker-compose ACCOUNT
if grep -q 'ACCOUNT=2529213858' docker-compose.yml; then
  sed -i "s/ACCOUNT=2529213858/ACCOUNT=${ACCOUNT}/" docker-compose.yml
  echo "updated docker-compose ACCOUNT=${ACCOUNT}"
fi

# webui auto login account
python3 - <<'PY'
import json
from pathlib import Path

path = Path("/home/ubuntu/napcat/config/webui.json")
data = json.loads(path.read_text(encoding="utf-8"))
data["autoLoginAccount"] = "5625523"
path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
print("updated webui autoLoginAccount=5625523")
PY

# disable stale quick-login config for old bot account
for old in onebot11_2529213858.json napcat_2529213858.json napcat_protocol_2529213858.json; do
  if [ -f "config/$old" ]; then
    mv "config/$old" "config/${old}.bak.$(date +%Y%m%d%H%M%S)"
    echo "archived config/$old"
  fi
done

docker compose up -d
sleep 5
docker logs napcat --tail 15 2>&1
curl -s http://127.0.0.1:8765/health || true
