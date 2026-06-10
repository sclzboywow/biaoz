#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import re
from typing import Any

from .baidu_remark import resolve_baidu_fs_id, version_has_downloadable_file
from .metadata_db import metadata_connection

RESOURCE_ID_OFFSET = 10_000_000


def _norm(text: str) -> str:
    return re.sub(r"[\s\-_/]+", "", (text or "").upper())


def _public_id(document_id: int | None, resource_id: int) -> int:
    if document_id:
        return int(document_id)
    return RESOURCE_ID_OFFSET + int(resource_id)


def _decode_public_id(public_id: int) -> tuple[int | None, int | None]:
    value = int(public_id)
    if value >= RESOURCE_ID_OFFSET:
        return None, value - RESOURCE_ID_OFFSET
    if value > 0:
        return value, None
    return None, None


def search_metadata_documents(query: str, limit: int = 10) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not limit or limit < 1:
        return []
    if not q:
        return []

    q_norm = _norm(q)
    like = f"%{q}%"
    like_norm = f"%{q_norm}%"
    sql = """
        WITH matched AS (
            SELECT
                sr.id AS resource_id,
                d.id AS document_id,
                COALESCE(NULLIF(BTRIM(d.standard_no), ''), NULLIF(BTRIM(sr.standard_no), '')) AS code,
                COALESCE(NULLIF(BTRIM(d.title), ''), sr.standard_name) AS title,
                COALESCE(NULLIF(BTRIM(d.category), ''), NULLIF(BTRIM(sr.resource_type), ''), '') AS category,
                CASE
                    WHEN dv.id IS NOT NULL AND (
                        dv.file_path LIKE 'baidupan:%%'
                        OR dv.remark LIKE '%%baidu_pan_sync=%%'
                        OR (
                            dv.file_path IS NOT NULL
                            AND BTRIM(dv.file_path) <> ''
                            AND dv.file_path NOT LIKE 'http%%'
                        )
                    ) THEN 1
                    ELSE 0
                END AS has_file,
                CASE
                    WHEN REPLACE(REPLACE(REPLACE(UPPER(COALESCE(d.standard_no, sr.standard_no)), ' ', ''), '-', ''), '/', '') = %(q_norm)s THEN 0
                    WHEN COALESCE(d.standard_no, sr.standard_no) ILIKE %(like)s THEN 1
                    WHEN sr.standard_name ILIKE %(like)s THEN 2
                    ELSE 3
                END AS relevance
            FROM standard_resources sr
            LEFT JOIN LATERAL (
                SELECT d2.*
                FROM documents d2
                WHERE (
                    (d2.normalized_standard_no IS NOT NULL AND sr.normalized_standard_no IS NOT NULL AND d2.normalized_standard_no = sr.normalized_standard_no)
                    OR (d2.standard_no IS NOT NULL AND sr.standard_no IS NOT NULL AND d2.standard_no = sr.standard_no)
                )
                ORDER BY d2.id DESC
                LIMIT 1
            ) d ON TRUE
            LEFT JOIN document_versions dv
                ON dv.document_id = d.id
               AND dv.is_current IS TRUE
            WHERE sr.standard_no IS NOT NULL
              AND BTRIM(sr.standard_no) <> ''
              AND (
                    sr.standard_no ILIKE %(like)s
                 OR sr.standard_name ILIKE %(like)s
                 OR COALESCE(sr.keywords, '') ILIKE %(like)s
                 OR COALESCE(sr.normalized_standard_no, '') LIKE %(like_norm)s
                 OR REPLACE(REPLACE(REPLACE(UPPER(sr.standard_no), ' ', ''), '-', ''), '/', '') LIKE %(like_norm)s
              )
        ),
        deduped AS (
            SELECT DISTINCT ON (resource_id)
                resource_id,
                document_id,
                code,
                title,
                category,
                has_file,
                relevance
            FROM matched
            ORDER BY resource_id, has_file DESC, relevance ASC, document_id DESC NULLS LAST
        )
        SELECT resource_id, document_id, code, title, category, has_file
        FROM deduped
        ORDER BY relevance ASC, has_file DESC, resource_id ASC
        LIMIT %(limit)s
    """
    params = {"like": like, "like_norm": like_norm, "q_norm": q_norm, "limit": int(limit)}

    with metadata_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    results: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for resource_id, document_id, code, title, category, has_file in rows:
        if not code:
            continue
        dedupe_key = _norm(code)
        if dedupe_key in seen_codes:
            continue
        seen_codes.add(dedupe_key)
        results.append(
            {
                "id": _public_id(document_id, resource_id),
                "document_id": document_id,
                "resource_id": resource_id,
                "code": code,
                "title": title or code,
                "category": category or "",
                "ticket_cost": 1,
                "has_file": bool(has_file),
            }
        )
    return results


def lookup_metadata_document(public_id: int) -> dict[str, Any] | None:
    document_id, resource_id = _decode_public_id(public_id)
    with metadata_connection() as conn:
        with conn.cursor() as cur:
            if document_id:
                cur.execute(
                    """
                    SELECT d.id, d.standard_no, d.title, COALESCE(d.category, ''), dv.file_path, dv.remark
                    FROM documents d
                    LEFT JOIN document_versions dv
                      ON dv.document_id = d.id AND dv.is_current IS TRUE
                    WHERE d.id = %s
                    LIMIT 1
                    """,
                    (document_id,),
                )
                row = cur.fetchone()
                if row:
                    return {
                        "document_id": row[0],
                        "resource_id": None,
                        "code": row[1] or "",
                        "title": row[2] or row[1] or "",
                        "category": row[3] or "",
                        "file_path": row[4],
                        "remark": row[5],
                        "has_file": version_has_downloadable_file(file_path=row[4], remark=row[5]),
                    }
            if resource_id:
                cur.execute(
                    """
                    SELECT sr.id, sr.standard_no, sr.standard_name, COALESCE(sr.resource_type, ''),
                           d.id, d.title, COALESCE(d.category, ''), dv.file_path, dv.remark
                    FROM standard_resources sr
                    LEFT JOIN LATERAL (
                        SELECT d2.*
                        FROM documents d2
                        WHERE (
                            (d2.normalized_standard_no IS NOT NULL AND sr.normalized_standard_no IS NOT NULL AND d2.normalized_standard_no = sr.normalized_standard_no)
                            OR (d2.standard_no IS NOT NULL AND sr.standard_no IS NOT NULL AND d2.standard_no = sr.standard_no)
                        )
                        ORDER BY d2.id DESC
                        LIMIT 1
                    ) d ON TRUE
                    LEFT JOIN document_versions dv
                      ON dv.document_id = d.id AND dv.is_current IS TRUE
                    WHERE sr.id = %s
                    LIMIT 1
                    """,
                    (resource_id,),
                )
                row = cur.fetchone()
                if row:
                    doc_id = row[4]
                    file_path = row[7]
                    remark = row[8]
                    return {
                        "document_id": doc_id,
                        "resource_id": row[0],
                        "code": row[1] or "",
                        "title": (row[5] or row[2] or row[1] or ""),
                        "category": row[6] or row[3] or "",
                        "file_path": file_path,
                        "remark": remark,
                        "has_file": version_has_downloadable_file(file_path=file_path, remark=remark),
                    }
    return None


def create_baidu_share_link(fs_id: str) -> dict[str, str] | None:
    access_token = os.getenv("BAIDU_NETDISK_ACCESS_TOKEN", "").strip()
    if not access_token or not fs_id:
        return None
    try:
        import requests
    except ImportError:
        return None

    resp = requests.post(
        "https://pan.baidu.com/rest/2.0/xpan/share",
        params={"method": "set", "access_token": access_token},
        data={"fid_list": f"[{fs_id}]", "period": 7, "schannel": 4, "channel_list": "[]"},
        timeout=20,
    )
    if resp.status_code != 200:
        return None
    payload = resp.json()
    if payload.get("errno") not in (0, None):
        return None
    link = str(payload.get("link") or "")
    if not link:
        return None
    pwd = str(payload.get("pwd") or payload.get("password") or "")
    return {"pan_share_url": link, "pan_extract_code": pwd}
