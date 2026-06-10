"""One-off: verify WPS multidimensional table read via AirScript webhook."""
from __future__ import annotations

import json
import os
import time
import urllib.request

URL = os.getenv(
    "WPS_DBT_WEBHOOK_URL",
    "https://365.kdocs.cn/api/v3/ide/file/296498309264/script/V2-V8JCUpZX1qTQRg5B39Jec/sync_task",
)
TOKEN = os.getenv("WPS_AIRSCRIPT_TOKEN", "").strip()


def call(argv: dict, timeout: int = 120) -> dict:
    body = json.dumps({"Context": {"argv": argv}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "AirScript-Token": TOKEN,
        },
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    elapsed = time.time() - t0
    result_raw = raw.get("data", {}).get("result")
    try:
        result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
    except Exception as exc:
        result = {"parse_error": str(exc), "raw": str(result_raw)[:500]}
    return {
        "status": raw.get("status"),
        "api_error": raw.get("error"),
        "elapsed_s": round(elapsed, 2),
        "result": result,
    }


def main() -> None:
    if not TOKEN:
        raise SystemExit("WPS_AIRSCRIPT_TOKEN is required")
    print("=== 测试1: 默认 read (limit=10) ===")
    r1 = call({"action": "read"})
    res1 = r1["result"]
    print(f"status={r1['status']} elapsed={r1['elapsed_s']}s success={res1.get('success')}")
    records1 = res1.get("records") or []
    print(f"count={len(records1)}")
    if not res1.get("success"):
        print("ERROR:", res1)
        return
    rec = records1[0]
    fields = rec.get("fields") or {}
    print("首条 id:", rec.get("id"))
    print("字段:", list(fields.keys()))
    print("文件编号:", fields.get("文件编号"))
    print("文件名称:", (fields.get("文件名称") or "")[:60])
    print("实施状态:", fields.get("实施状态"))
    link = fields.get("链接")
    if isinstance(link, list) and link:
        addr = link[0].get("address", link[0]) if isinstance(link[0], dict) else link[0]
        print("链接:", str(addr)[:80])

    print("\n=== 测试2: read limit=100 ===")
    r2 = call({"action": "read", "limit": 100})
    res2 = r2["result"]
    records2 = res2.get("records") or []
    print(f"success={res2.get('success')} count={len(records2)} elapsed={r2['elapsed_s']}s")
    if records2:
        nums = [x["fields"].get("编号") for x in records2 if x.get("fields") and x["fields"].get("编号") is not None]
        if nums:
            print("编号范围:", min(nums), "-", max(nums))

    print("\n=== 测试3: read limit=500 (探测单次上限) ===")
    try:
        r3 = call({"action": "read", "limit": 500}, timeout=180)
        res3 = r3["result"]
        records3 = res3.get("records") or []
        print(f"success={res3.get('success')} count={len(records3)} elapsed={r3['elapsed_s']}s")
        if not res3.get("success"):
            print("error:", res3.get("error"))
    except Exception as exc:
        print("FAILED:", exc)

    print("\n=== 测试4: 空 argv (应失败) ===")
    r4 = call({})
    res4 = r4["result"]
    print(f"success={res4.get('success')} error={res4.get('error')}")

    print("\n=== 测试5: filter 实施状态=现行 limit=5 ===")
    r5 = call({"action": "read", "limit": 5, "filter": {"实施状态": "现行"}})
    res5 = r5["result"]
    records5 = res5.get("records") or []
    print(f"success={res5.get('success')} count={len(records5)}")
    for item in records5[:3]:
        f = item.get("fields") or {}
        print(" -", (f.get("文件编号") or "")[:50], "|", f.get("实施状态"))

    print("\n结论: 读取", "成功" if res1.get("success") and len(records1) > 0 else "失败")


if __name__ == "__main__":
    main()
