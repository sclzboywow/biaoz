#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deliver download result (text + optional file) to QQ group via qq-ai-bot."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .cache_cleanup import cleanup_local_cache
from .download_file import download_document_file
from .service import select_download


def _bot_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = os.getenv("BOT_API_BASE", "http://127.0.0.1:8765").rstrip("/")
    secret = os.getenv("BOT_INTERNAL_SECRET", "")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={"Content-Type": "application/json", "X-Internal-Secret": secret},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return {"ok": True, "status": resp.status, "body": json.loads(resp.read().decode())}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw}
        return {"ok": False, "status": exc.code, "body": body}


def deliver_download_to_group(
    qq_user_id: str,
    group_id: str,
    index: int,
    *,
    send_text: bool = True,
    send_file: bool = True,
) -> dict[str, Any]:
    result = select_download(qq_user_id, group_id, index)
    if not result.get("success"):
        return result
    if result.get("need_pay"):
        return result

    delivery: dict[str, Any] = {"deliver": {}}
    message = result.get("message") or ""
    display_name = (result.get("file") or {}).get("display_name") or ""

    if send_text and message:
        delivery["deliver"]["text"] = _bot_post(
            "/internal/send-group-msg",
            {"group_id": int(group_id), "text": message},
        )

    if send_file:
        doc_id = int((result.get("document") or {}).get("id") or 0)
        if doc_id:
            try:
                file_path = download_document_file(doc_id, display_name=display_name or None)
            except Exception as exc:
                delivery["deliver"]["file"] = {"ok": False, "error": str(exc)}
                file_path = None
            if file_path and file_path.exists():
                delivery["deliver"]["file"] = _bot_post(
                    "/internal/qq-file/send-group",
                    {
                        "group_id": int(group_id),
                        "file_path": str(file_path),
                        "file_name": display_name or file_path.name,
                        "mode": "chat",
                    },
                )
                delivery["deliver"]["file_path"] = str(file_path)
            elif "file" not in delivery["deliver"]:
                delivery["deliver"]["file"] = {"ok": False, "error": "download failed"}

    try:
        delivery["cache_cleanup"] = cleanup_local_cache()
    except Exception as exc:
        delivery["cache_cleanup"] = {"error": str(exc)}

    result.update(delivery)
    return result
