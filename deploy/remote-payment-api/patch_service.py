#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply metadata search integration patches to remote payment-api/library/service.py"""

from __future__ import annotations

from pathlib import Path

SERVICE_PATH = Path(__file__).resolve().parent / "service.py"


def main() -> int:
    text = SERVICE_PATH.read_text(encoding="utf-8")
    if "metadata_integration" in text:
        print("service.py already patched")
        return 0

    old_import = "from .db import get_library_db_path, init_library_db\n"
    new_import = old_import + "from .metadata_integration import metadata_search, resolve_metadata_share\n"
    if old_import not in text:
        raise SystemExit("import anchor not found")
    text = text.replace(old_import, new_import, 1)

    old_search = "def search_documents(query: str, limit: int = 10) -> List[Dict[str, Any]]:\n    init_library_db()\n"
    new_search = (
        "def search_documents(query: str, limit: int = 10) -> List[Dict[str, Any]]:\n"
        "    metadata_results = metadata_search(query, limit=limit)\n"
        "    if metadata_results is not None:\n"
        "        return metadata_results\n\n"
        "    init_library_db()\n"
    )
    if old_search not in text:
        raise SystemExit("search_documents anchor not found")
    text = text.replace(old_search, new_search, 1)

    old_share = "        share = _resolve_share_link(document_id)\n        if not share.get(\"ok\"):\n"
    new_share = (
        "        if metadata_search_enabled():\n"
        "            share = resolve_metadata_share(document_id)\n"
        "        else:\n"
        "            share = _resolve_share_link(document_id)\n"
        "        if not share.get(\"ok\"):\n"
    )
    if old_share not in text:
        raise SystemExit("select_download share anchor not found")
    text = text.replace(old_share, new_share, 1)

    old_doc = "        doc = cur.fetchone()\n        if not doc:\n            cur.execute(\"ROLLBACK\")\n            return {\"success\": False, \"message\": \"资料不存在或已下架。\"}\n\n        if metadata_search_enabled():"
    # Need different approach - replace doc fetch block when metadata enabled

    old_doc_block = """        cur.execute(
            \"\"\"
            SELECT id, code, title, category, ticket_cost
            FROM documents
            WHERE id = ? AND is_active = 1 AND status = 'active'
            \"\"\",
            (document_id,),
        )
        doc = cur.fetchone()
        if not doc:
            cur.execute("ROLLBACK")
            return {"success": False, "message": "资料不存在或已下架。"}

        if metadata_search_enabled():"""

    new_doc_block = """        doc_row = None
        if metadata_search_enabled():
            meta_doc = lookup_metadata_document(document_id)
            if not meta_doc:
                cur.execute("ROLLBACK")
                return {"success": False, "message": "资料不存在或已下架。"}
            doc_row = (
                document_id,
                meta_doc.get("code") or "",
                meta_doc.get("title") or "",
                meta_doc.get("category") or "",
                1,
            )
        else:
            cur.execute(
                \"\"\"
                SELECT id, code, title, category, ticket_cost
                FROM documents
                WHERE id = ? AND is_active = 1 AND status = 'active'
                \"\"\",
                (document_id,),
            )
            doc_row = cur.fetchone()
        if not doc_row:
            cur.execute("ROLLBACK")
            return {"success": False, "message": "资料不存在或已下架。"}
        doc = doc_row

        if metadata_search_enabled():"""

    if old_doc_block not in text:
        raise SystemExit("doc block anchor not found")
    text = text.replace(old_doc_block, new_doc_block, 1)

    text = text.replace(
        "from .metadata_integration import metadata_search, resolve_metadata_share\n",
        "from .metadata_integration import metadata_search, resolve_metadata_share\n"
        "from .metadata_search import lookup_metadata_document\n"
        "from .metadata_db import metadata_search_enabled\n",
        1,
    )

    old_insert = """            INSERT INTO download_logs (
                user_id, group_id, document_id, pan_asset_id, share_link_id,
                ticket_cost, pan_share_url, pan_extract_code, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'success', ?)
            \"\"\",
            (
                user_id,
                str(group_id),
                document_id,
                share["pan_asset_id"],
                share["share_link_id"],
                ticket_cost,
                share["pan_share_url"],
                share["pan_extract_code"],
                now,
            ),
        )"""

    new_insert = """            INSERT INTO download_logs (
                user_id, group_id, document_id, pan_asset_id, share_link_id,
                ticket_cost, pan_share_url, pan_extract_code, status, created_at,
                doc_code, doc_title
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'success', ?, ?, ?)
            \"\"\",
            (
                user_id,
                str(group_id),
                document_id,
                share.get("pan_asset_id"),
                share.get("share_link_id"),
                ticket_cost,
                share["pan_share_url"],
                share["pan_extract_code"],
                now,
                doc[1],
                doc[2],
            ),
        )"""

    if old_insert not in text:
        raise SystemExit("download_logs insert anchor not found")
    text = text.replace(old_insert, new_insert, 1)

    old_wallet = """        SELECT d.code, d.title, dl.created_at
        FROM download_logs dl
        JOIN documents d ON d.id = dl.document_id
        WHERE dl.user_id = ? AND dl.status = 'success'
        ORDER BY dl.id DESC
        LIMIT 5"""

    new_wallet = """        SELECT COALESCE(dl.doc_code, d.code), COALESCE(dl.doc_title, d.title), dl.created_at
        FROM download_logs dl
        LEFT JOIN documents d ON d.id = dl.document_id
        WHERE dl.user_id = ? AND dl.status = 'success'
        ORDER BY dl.id DESC
        LIMIT 5"""

    text = text.replace(old_wallet, new_wallet, 1)

    old_resend = """        SELECT dl.document_id, dl.pan_share_url, dl.pan_extract_code, dl.created_at,
               d.code, d.title
        FROM download_logs dl
        JOIN documents d ON d.id = dl.document_id
        WHERE dl.user_id = ? AND dl.status = 'success'
        ORDER BY dl.id DESC
        LIMIT 1"""

    new_resend = """        SELECT dl.document_id, dl.pan_share_url, dl.pan_extract_code, dl.created_at,
               COALESCE(dl.doc_code, d.code), COALESCE(dl.doc_title, d.title)
        FROM download_logs dl
        LEFT JOIN documents d ON d.id = dl.document_id
        WHERE dl.user_id = ? AND dl.status = 'success'
        ORDER BY dl.id DESC
        LIMIT 1"""

    text = text.replace(old_resend, new_resend, 1)

    SERVICE_PATH.write_text(text, encoding="utf-8")
    print("service.py patched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
