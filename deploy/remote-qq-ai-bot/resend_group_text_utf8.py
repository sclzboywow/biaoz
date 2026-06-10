#!/usr/bin/env python3
import json
import urllib.request

msg = (
    "\u005b\u6d4b\u8bd5\u8bf4\u660e\u005d "
    "\u521a\u624d\u7684\u6587\u4ef6\u53d1\u9001\u63a2\u9488\u5df2\u6210\u529f\uff1a"
    "\u804a\u5929\u9644\u4ef6 txt x2 + \u7fa4\u6587\u4ef6\u76d8 x1\u3002"
    "\u6b64\u524d\u6587\u5b57\u4e71\u7801\u662f SSH/curl \u7f16\u7801\u95ee\u9898\uff0c"
    "\u672c\u6761\u4e3a UTF-8 \u91cd\u53d1\u3002"
)
payload = {"group_id": 808238349, "message": msg}
req = urllib.request.Request(
    "http://127.0.0.1:3001/send_group_msg",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    print(resp.read().decode("utf-8", errors="replace"))
