#!/bin/bash
set -euo pipefail

GROUP_ID="${1:-808238349}"
TEST_FILE="/home/ubuntu/qq-ai-bot/qq-file-send-test.txt"
HTTP_PORT=3001
OB_CFG="/home/ubuntu/napcat/config/onebot11_2529213858.json"

python3 - <<'PY'
import json
from pathlib import Path

cfg_path = Path("/home/ubuntu/napcat/config/onebot11_2529213858.json")
cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
servers = cfg.setdefault("network", {}).setdefault("httpServers", [])
if not any(s.get("port") == 3001 and s.get("enable") for s in servers):
    servers.append({
        "name": "local-test-http",
        "enable": True,
        "host": "127.0.0.1",
        "port": 3001,
        "accessToken": "",
        "messagePostFormat": "array",
        "debug": False,
    })
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("patched httpServers")
else:
    print("httpServers already enabled")
PY

docker restart napcat >/dev/null
sleep 8

for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${HTTP_PORT}/get_status" >/dev/null 2>&1; then
    echo "napcat http ready"
    break
  fi
  sleep 2
done

TS=$(date -Iseconds)
cat > "$TEST_FILE" <<EOF
QQ 群文件发送测试
群号: ${GROUP_ID}
时间: ${TS}
说明: NapCat upload_group_file + send_group_msg 探针
EOF

INTRO="[文件发送测试] ${TS} — 下面尝试以聊天附件形式发送 txt 文件"

curl -sS -X POST "http://127.0.0.1:${HTTP_PORT}/send_group_msg" \
  -H 'Content-Type: application/json' \
  -d "{\"group_id\":${GROUP_ID},\"message\":\"${INTRO}\"}"
echo

echo "--- send_group_msg file segment ---"
python3 - <<PY
import json, urllib.request
group_id = int("${GROUP_ID}")
file_path = "${TEST_FILE}"
intro = "${INTRO}"
payload = {
    "group_id": group_id,
    "message": [
        {"type": "text", "data": {"text": intro + " (file segment)"}},
        {"type": "file", "data": {"file": file_path, "name": "qq-file-send-test.txt"}},
    ],
}
req = urllib.request.Request(
    "http://127.0.0.1:${HTTP_PORT}/send_group_msg",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=60) as resp:
    print(resp.read().decode("utf-8", errors="replace"))
PY

echo "--- upload_group_file ---"
python3 - <<PY
import json, urllib.request
payload = {
    "group_id": int("${GROUP_ID}"),
    "file": "${TEST_FILE}",
    "name": "qq-file-send-test.txt",
}
req = urllib.request.Request(
    "http://127.0.0.1:${HTTP_PORT}/upload_group_file",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=120) as resp:
    print(resp.read().decode("utf-8", errors="replace"))
PY
