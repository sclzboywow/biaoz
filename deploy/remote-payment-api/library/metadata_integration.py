#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, Optional

from .baidu_remark import resolve_baidu_fs_id
from .db import get_library_db_path, init_library_db
from .metadata_db import metadata_search_enabled
from .metadata_search import create_baidu_share_link, lookup_metadata_document, search_metadata_documents
import sqlite3


def resolve_metadata_share(document_id: int) -> Dict[str, Any]:
    doc = lookup_metadata_document(document_id)
    if not doc:
        return {"ok": False, "message": "资料不存在或已下架。"}
    if not doc.get("has_file"):
        return {
            "ok": False,
            "message": "该标准已在全库元数据中，但暂未配置可下载文件。",
        }

    fs_id = resolve_baidu_fs_id(file_path=doc.get("file_path"), remark=doc.get("remark"))
    if fs_id:
        share = create_baidu_share_link(fs_id)
        if share:
            return {
                "ok": True,
                "document": doc,
                "pan_share_url": share["pan_share_url"],
                "pan_extract_code": share.get("pan_extract_code") or "",
                "period_days": share.get("period_days"),
                "share_id": share.get("share_id"),
                "pan_short_url": share.get("pan_short_url"),
            }

    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    code_norm = (doc.get("code") or "").replace(" ", "").replace("-", "").upper()
    cur.execute(
        """
        SELECT psl.pan_share_url, psl.pan_extract_code
        FROM documents d
        JOIN pan_assets pa ON pa.document_id = d.id
        JOIN pan_share_links psl ON psl.pan_asset_id = pa.id AND psl.is_active = 1
        WHERE REPLACE(REPLACE(REPLACE(UPPER(d.code), ' ', ''), '-', ''), '/', '') = ?
        ORDER BY psl.id DESC
        LIMIT 1
        """,
        (code_norm,),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "ok": True,
            "document": doc,
            "pan_share_url": row[0],
            "pan_extract_code": row[1] or "",
        }

    return {
        "ok": False,
        "message": "该标准已入库，但暂未生成百度网盘分享链接，请联系管理员处理。",
    }


def metadata_search(query: str, limit: int = 10):
    if not metadata_search_enabled():
        return None
    return search_metadata_documents(query, limit=limit)
