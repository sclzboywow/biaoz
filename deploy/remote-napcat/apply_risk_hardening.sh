#!/usr/bin/env bash
# 降低 QQ 安全中心「外挂/容器/Linux 云主机」误判概率。
# 需在服务器 /home/ubuntu/napcat 下执行；改 hostname 后需重新扫码登录一次。
set -euo pipefail

NAPCAT_DIR="${NAPCAT_DIR:-/home/ubuntu/napcat}"
NEW_HOSTNAME="${NEW_HOSTNAME:-DESKTOP-PC7K2M}"
CONFIG="$NAPCAT_DIR/config/napcat.json"

python3 - <<'PY'
import json
from pathlib import Path
import os

cfg_dir = Path(os.environ["NAPCAT_DIR"]) / "config"
for path in sorted(cfg_dir.glob("napcat*.json")):
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    bypass = data.setdefault("bypass", {})
    for key in ("hook", "window", "module", "process", "container", "js"):
        bypass[key] = True
    data["o3HookMode"] = data.get("o3HookMode", 1)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("updated", path.name, bypass)
PY

if [[ "$(hostname)" == VM-*-ubuntu ]] || [[ "$(hostname)" == *ubuntu* ]]; then
  echo "setting host hostname -> $NEW_HOSTNAME"
  sudo hostnamectl set-hostname "$NEW_HOSTNAME"
  sudo sed -i "/127.0.1.1/d" /etc/hosts || true
  echo "127.0.1.1 $NEW_HOSTNAME" | sudo tee -a /etc/hosts >/dev/null
fi

cd "$NAPCAT_DIR"
docker compose up -d --force-recreate
echo "done; check WebUI bypass page and re-login if QQ kicked offline"
