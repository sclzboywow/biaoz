#!/usr/bin/env python3
"""One-off: send a test file to a QQ group via NapCat OneBot WS (reverse connection)."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import websockets


async def send_via_bot_ws(group_id: int, file_path: Path, intro: str) -> dict:
    """Use existing NapCat->bot WS by posting to a local helper endpoint if available."""
    raise NotImplementedError


async def send_via_napcat_http(group_id: int, file_path: Path, intro: str, *, base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    message = [
        {"type": "text", "data": {"text": intro}},
        {"type": "file", "data": {"file": str(file_path), "name": file_path.name}},
    ]
    payload = {"group_id": group_id, "message": message}
    async with httpx.AsyncClient(timeout=60.0) as client:
        for path in ("/onebot/v11/send_group_msg", "/api/send_group_msg", "/api/SendGroupMsg"):
            resp = await client.post(f"{base_url.rstrip('/')}{path}", headers=headers, json=payload)
            if resp.status_code == 404:
                continue
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:500]}
            return {"path": path, "status": resp.status_code, "data": data}
    return {"error": "no working onebot http endpoint"}


async def send_via_upload_group_file(
    group_id: int, file_path: Path, intro: str, *, base_url: str, token: str
) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        intro_resp = await client.post(
            f"{base_url.rstrip('/')}/onebot/v11/send_group_msg",
            headers=headers,
            json={"group_id": group_id, "message": intro},
        )
        upload_resp = await client.post(
            f"{base_url.rstrip('/')}/onebot/v11/upload_group_file",
            headers=headers,
            json={"group_id": group_id, "file": str(file_path), "name": file_path.name},
        )
        try:
            upload_data = upload_resp.json()
        except Exception:
            upload_data = {"raw": upload_resp.text[:500]}
        return {
            "intro_status": intro_resp.status_code,
            "upload_status": upload_resp.status_code,
            "upload_data": upload_data,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group-id", type=int, required=True)
    parser.add_argument("--file", type=Path, default=Path("/tmp/qq-file-test.txt"))
    parser.add_argument("--napcat-http", default="http://127.0.0.1:6099")
    parser.add_argument("--webui-config", default="/home/ubuntu/napcat/config/webui.json")
    args = parser.parse_args()

    token = json.loads(Path(args.webui_config).read_text(encoding="utf-8"))["token"]
    intro = (
        f"[文件发送测试] {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"群号: {args.group_id}\n"
        f"文件: {args.file.name}"
    )
    if not args.file.exists():
        args.file.write_text(f"QQ bot file send test\n{intro}\n", encoding="utf-8")

    result = asyncio.run(
        send_via_upload_group_file(
            args.group_id,
            args.file,
            intro,
            base_url=args.napcat_http,
            token=token,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = result.get("upload_status") == 200 and str(result.get("upload_data", {})).find("retcode") == -1
    if result.get("upload_status") not in (200, 0) and "retcode" in str(result.get("upload_data")):
        # NapCat often returns retcode inside JSON even on HTTP 200
        data = result.get("upload_data") or {}
        ok = isinstance(data, dict) and data.get("retcode") in (0, "0", None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
