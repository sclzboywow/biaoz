#!/usr/bin/env python3
import json
import urllib.request

GROUP_ID = 808238349
FILE_ID = "/fd615d0f-bd00-4153-a8e2-252b8f62c508"
BUSID = 102
HTTP = "http://127.0.0.1:3001"


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{HTTP}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


url_resp = post("/get_group_file_url", {"group_id": GROUP_ID, "file_id": FILE_ID, "busid": BUSID})
url = url_resp["data"]["url"]
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=120) as resp:
    head = resp.read(5)
    cl = resp.headers.get("Content-Length")
print("download_url_prefix", url[:90])
print("content_length", cl)
print("magic", head)
print("is_pdf", head.startswith(b"%PDF"))
