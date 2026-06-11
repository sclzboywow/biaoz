#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download document bytes from Baidu Pan to a local path with Chinese filename."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from .baidu_client import get_access_token
from .baidu_remark import resolve_baidu_fs_id
from .cache_cleanup import cleanup_local_cache
from .download_delivery import build_chinese_filename
from .metadata_search import lookup_metadata_document


def download_document_file(
    document_id: int,
    *,
    save_dir: str | Path | None = None,
    display_name: str | None = None,
) -> Path | None:
    doc = lookup_metadata_document(document_id)
    if not doc:
        return None
    fs_id = resolve_baidu_fs_id(file_path=doc.get("file_path"), remark=doc.get("remark"))
    if not fs_id:
        return None

    filename = display_name or build_chinese_filename(doc.get("code"), doc.get("title"))
    out_dir = Path(save_dir or os.getenv("LIBRARY_DOWNLOAD_DIR", "/home/ubuntu/qq-ai-bot/downloads/delivery"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename.replace("/", "_")

    token = get_access_token()
    meta_url = "https://pan.baidu.com/rest/2.0/xpan/multimedia?" + urllib.parse.urlencode(
        {"method": "filemetas", "access_token": token, "openapi": "xpansdk"}
    )
    meta_body = urllib.parse.urlencode({"fsids": json.dumps([int(fs_id)]), "dlink": "1"}).encode()
    req = urllib.request.Request(meta_url, data=meta_body, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        meta = json.loads(resp.read().decode())
    items = meta.get("list") or []
    if not items:
        return None
    dlink = items[0].get("dlink")
    if not dlink:
        return None

    sep = "&" if "?" in dlink else "?"
    dl_url = f"{dlink}{sep}access_token={urllib.parse.quote(token, safe='')}"
    dl_req = urllib.request.Request(dl_url, headers={"User-Agent": "pan.baidu.com"})
    with urllib.request.urlopen(dl_req, timeout=300) as resp:
        out_path.write_bytes(resp.read())
    try:
        cleanup_local_cache()
    except OSError:
        pass
    return out_path
