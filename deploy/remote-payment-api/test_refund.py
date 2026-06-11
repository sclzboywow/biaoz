#!/usr/bin/env python3
"""Call ticket-order refund API on localhost."""
import json
import sys
import urllib.error
import urllib.request

ORDER_NO = sys.argv[1] if len(sys.argv) > 1 else "T1781142147462"
REASON = sys.argv[2] if len(sys.argv) > 2 else "admin refund"
SECRET = sys.argv[3] if len(sys.argv) > 3 else "qq-payment-internal-2026"

payload = {"order_no": ORDER_NO, "reason": REASON}
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/internal/ticket-order/refund",
    data=json.dumps(payload).encode(),
    headers={
        "Content-Type": "application/json",
        "X-Internal-Secret": SECRET,
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req) as resp:
        print(resp.read().decode())
except urllib.error.HTTPError as exc:
    print(exc.code, exc.read().decode())
