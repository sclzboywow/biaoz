#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

BAIDU_PAN_SYNC_PREFIX = "baidu_pan_sync="


def iter_baidu_pan_sync_entries(remark: str | None) -> list[dict[str, Any]]:
    if not remark:
        return []
    entries: list[dict[str, Any]] = []
    for line in remark.splitlines():
        if not line.startswith(BAIDU_PAN_SYNC_PREFIX):
            continue
        raw = line[len(BAIDU_PAN_SYNC_PREFIX) :]
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def latest_baidu_pan_sync(remark: str | None) -> dict[str, Any] | None:
    entries = iter_baidu_pan_sync_entries(remark)
    return entries[-1] if entries else None


def parse_fs_id_from_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    if "#fs_id=" in uri:
        return uri.split("#fs_id=", 1)[1].split("&", 1)[0] or None
    parsed = urlparse(uri)
    query = parse_qs(parsed.query)
    fs_id = query.get("fs_id", [None])[0]
    return str(fs_id) if fs_id else None


def resolve_baidu_fs_id(*, file_path: str | None, remark: str | None) -> str | None:
    fs_id = parse_fs_id_from_uri(file_path)
    if fs_id:
        return fs_id
    latest = latest_baidu_pan_sync(remark)
    if not latest or latest.get("status") == "failed":
        return None
    fs_id = latest.get("fs_id")
    if fs_id:
        return str(fs_id)
    return parse_fs_id_from_uri(str(latest.get("remote_uri") or ""))


def version_has_downloadable_file(*, file_path: str | None, remark: str | None) -> bool:
    if file_path and file_path.strip():
        if file_path.startswith("baidupan:"):
            return True
        if not file_path.startswith("http"):
            return True
    latest = latest_baidu_pan_sync(remark)
    return bool(latest and latest.get("status") != "failed" and latest.get("remote_uri"))
