#!/usr/bin/env bash
set -euo pipefail
REMOTE=ubuntu@111.231.22.77
KEY="${HOME}/.ssh/id_ed25519"
DIR="$(cd "$(dirname "$0")" && pwd)"
scp -i "$KEY" -o BatchMode=yes \
  "$DIR/app.py" \
  "$DIR/ai/templates.py" \
  "$REMOTE:/tmp/qq-bot-deploy/"
ssh -i "$KEY" -o BatchMode=yes "$REMOTE" 'bash -s' <<'EOF'
set -euo pipefail
mkdir -p /home/ubuntu/qq-ai-bot/ai
cp /tmp/qq-bot-deploy/app.py /home/ubuntu/qq-ai-bot/app.py
cp /tmp/qq-bot-deploy/templates.py /home/ubuntu/qq-ai-bot/ai/templates.py
python3 - <<'PY'
from pathlib import Path
p = Path("/home/ubuntu/qq-ai-bot/.env")
text = p.read_text(encoding="utf-8") if p.exists() else ""
updates = {
    "AUTO_ACCEPT_GROUP": "true",
    "GROUP_ACCEPT_DELAY_MIN": "2",
    "GROUP_ACCEPT_DELAY_MAX": "5",
    "GROUP_WELCOME_ENABLED": "true",
    "GROUP_WELCOME_DELAY_SECONDS": "1.5",
}
lines = text.splitlines()
keys = set()
out = []
for line in lines:
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k = line.split("=", 1)[0].strip()
    if k in updates:
        out.append(f"{k}={updates[k]}")
        keys.add(k)
    else:
        out.append(line)
for k, v in updates.items():
    if k not in keys:
        out.append(f"{k}={v}")
p.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print("env_updated")
PY
sudo systemctl restart qq-ai-bot.service
sleep 2
curl -s http://127.0.0.1:8765/health
EOF
