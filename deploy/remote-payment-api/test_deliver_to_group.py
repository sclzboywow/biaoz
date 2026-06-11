#!/usr/bin/env python3
import json
import os
import urllib.request

SECRET = os.getenv("BOT_INTERNAL_SECRET", "qq-payment-internal-2026")
BASE = "http://127.0.0.1:8000"
QQ = os.getenv("E2E_QQ_USER", "215836668")
GROUP = os.getenv("E2E_GROUP_ID", "808238349")


def post(path, payload):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Internal-Secret": SECRET},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


search = urllib.request.urlopen(
    urllib.request.Request(
        f"{BASE}/api/search-sessions",
        data=json.dumps({"qq_user_id": QQ, "group_id": GROUP, "query_text": "GB50016"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    ),
    timeout=60,
)
print("search", search.read().decode()[:200])
result = post(
    "/api/internal/download/deliver-to-group",
    {"qq_user_id": QQ, "group_id": GROUP, "index": 1, "send_text": True, "send_file": True},
)
print(json.dumps({k: result.get(k) for k in ("success", "message", "file", "share", "deliver")}, ensure_ascii=False, indent=2))
print("display_name", (result.get("file") or {}).get("display_name"))
print("message_preview", (result.get("message") or "")[:300])
