#!/usr/bin/env python3
"""Probe NapCat for a recent group file message and try to download it."""
import json
import urllib.request

GROUP_ID = 808238349
KEYWORD = "16MG03"
HTTP = "http://127.0.0.1:3001"


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{HTTP}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def main() -> None:
    history = post("/get_group_msg_history", {"group_id": GROUP_ID, "message_seq": 0, "count": 30})
    print("=== get_group_msg_history retcode", history.get("retcode"), "===")
    messages = (history.get("data") or {}).get("messages") or []
    print("messages:", len(messages))

    target = None
    for item in messages:
        msg = item.get("message") or []
        raw = json.dumps(item, ensure_ascii=False)
        if KEYWORD in raw or any(
            seg.get("type") == "file"
            for seg in (msg if isinstance(msg, list) else [])
        ):
            print("\n--- candidate ---")
            print(json.dumps(item, ensure_ascii=False, indent=2)[:4000])
            if KEYWORD in raw:
                target = item

    if not target:
        print("\nNo target message with keyword found in recent history.")
        return

    message_id = target.get("message_id")
    print("\n=== get_msg message_id=", message_id, "===")
    detail = post("/get_msg", {"message_id": message_id})
    print(json.dumps(detail, ensure_ascii=False, indent=2)[:4000])

    segs = (detail.get("data") or {}).get("message") or []
    if not isinstance(segs, list):
        print("message is not segment array")
        return

    for seg in segs:
        if seg.get("type") != "file":
            continue
        data = seg.get("data") or {}
        print("\n=== file segment ===")
        print(json.dumps(data, ensure_ascii=False, indent=2))

        file_id = data.get("file_id") or data.get("file")
        busid = data.get("busid")
        if file_id:
            for api, payload in [
                ("/get_group_file_url", {"group_id": GROUP_ID, "file_id": file_id, "busid": busid}),
                ("/get_file", {"file_id": file_id, "busid": busid}),
            ]:
                if api == "/get_group_file_url" and not busid:
                    payload.pop("busid", None)
                try:
                    result = post(api, payload)
                    print(f"\n=== {api} ===")
                    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])
                except Exception as exc:
                    print(f"\n=== {api} failed: {exc} ===")

    print("\n=== get_group_root_files ===")
    roots = post("/get_group_root_files", {"group_id": GROUP_ID})
    files = (roots.get("data") or {}).get("files") or []
    print("root files:", len(files))
    for f in files[:20]:
        name = f.get("file_name") or f.get("name") or ""
        if KEYWORD in name or "\u5730\u6c9f" in name:
            print(json.dumps(f, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
