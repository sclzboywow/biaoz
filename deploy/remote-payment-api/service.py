#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import sqlite3
import time
import secrets
from typing import Any, Dict, List, Optional

from .constants import (
    ORDER_EXPIRE_SECONDS,
    RESEND_WINDOW_SECONDS,
    SEARCH_SESSION_TTL_SECONDS,
    TICKET_PACKS,
)
from .db import get_library_db_path, init_library_db
from .metadata_db import metadata_search_enabled
from .metadata_integration import metadata_search, resolve_metadata_share
from .metadata_search import lookup_metadata_document


def _now() -> float:
    return time.time()


def free_download_enabled() -> bool:
    return os.getenv("LIBRARY_FREE_DOWNLOAD", "false").lower() in {"1", "true", "yes", "on"}


def _norm(text: str) -> str:
    return re.sub(r"[\s\-_/]+", "", (text or "").upper())


def get_or_create_user(qq_user_id: str, nickname: Optional[str] = None) -> int:
    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    now = _now()
    cur.execute("SELECT id FROM lib_users WHERE qq_user_id = ?", (str(qq_user_id),))
    row = cur.fetchone()
    if row:
        user_id = row[0]
        if nickname:
            cur.execute(
                "UPDATE lib_users SET nickname = ?, updated_at = ? WHERE id = ?",
                (nickname, now, user_id),
            )
            conn.commit()
        conn.close()
        return user_id

    cur.execute(
        "INSERT INTO lib_users (qq_user_id, nickname, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (str(qq_user_id), nickname, now, now),
    )
    user_id = cur.lastrowid
    cur.execute(
        "INSERT INTO ticket_wallets (user_id, balance, created_at, updated_at) VALUES (?, 0, ?, ?)",
        (user_id, now, now),
    )
    conn.commit()
    conn.close()
    return user_id


def search_documents(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    metadata_results = metadata_search(query, limit=limit)
    if metadata_results is not None:
        return metadata_results

    init_library_db()
    q = (query or "").strip()
    if not q:
        return []

    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    q_norm = _norm(q)
    like = f"%{q}%"
    like_norm = f"%{q_norm}%"

    cur.execute(
        """
        SELECT DISTINCT d.id, d.code, d.title, d.category, d.ticket_cost
        FROM documents d
        LEFT JOIN document_aliases a ON a.document_id = d.id
        WHERE d.is_active = 1 AND d.status = 'active'
          AND (
            d.code LIKE ? OR d.title LIKE ? OR IFNULL(d.keywords, '') LIKE ?
            OR d.code LIKE ? OR a.alias LIKE ? OR a.alias_norm LIKE ?
            OR REPLACE(REPLACE(REPLACE(UPPER(d.code), ' ', ''), '-', ''), '/', '') LIKE ?
          )
        ORDER BY
          CASE WHEN REPLACE(REPLACE(REPLACE(UPPER(d.code), ' ', ''), '-', ''), '/', '') = ? THEN 0
               WHEN d.code LIKE ? THEN 1
               WHEN d.title LIKE ? THEN 2
               ELSE 3 END,
          d.id ASC
        LIMIT ?
        """,
        (like, like, like, like, like, like_norm, like_norm, q_norm, like, like, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "code": r[1],
            "title": r[2],
            "category": r[3] or "",
            "ticket_cost": r[4],
        }
        for r in rows
    ]


def create_search_session(
    qq_user_id: str,
    group_id: str,
    query_text: str,
    results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    user_id = get_or_create_user(qq_user_id)
    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    now = _now()
    expires_at = now + SEARCH_SESSION_TTL_SECONDS

    payload = []
    for idx, item in enumerate(results, start=1):
        payload.append(
            {
                "index": idx,
                "document_id": item["id"],
                "code": item.get("code"),
                "title": item.get("title"),
            }
        )

    cur.execute(
        """
        INSERT INTO search_sessions (user_id, group_id, query_text, results_json, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, str(group_id), query_text, json.dumps(payload, ensure_ascii=False), expires_at, now),
    )
    session_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "session_id": session_id,
        "expires_at": expires_at,
        "results": payload,
    }


def _get_active_session(user_id: int, group_id: str) -> Optional[Dict[str, Any]]:
    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, results_json, expires_at
        FROM search_sessions
        WHERE user_id = ? AND group_id = ? AND expires_at > ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, str(group_id), _now()),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "session_id": row[0],
        "results": json.loads(row[1]),
        "expires_at": row[2],
    }


def _resolve_share_link(document_id: int) -> Dict[str, Any]:
    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pa.id, psl.id, psl.pan_share_url, psl.pan_extract_code
        FROM pan_assets pa
        JOIN pan_share_links psl ON psl.pan_asset_id = pa.id AND psl.is_active = 1
        WHERE pa.document_id = ?
        ORDER BY psl.id DESC
        LIMIT 1
        """,
        (document_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"ok": False, "message": "该资料暂未配置下载链接，请联系管理员处理。"}
    return {
        "ok": True,
        "pan_asset_id": row[0],
        "share_link_id": row[1],
        "pan_share_url": row[2],
        "pan_extract_code": row[3] or "",
    }


def _get_wallet_balance(conn: sqlite3.Connection, user_id: int) -> int:
    cur = conn.cursor()
    cur.execute("SELECT balance FROM ticket_wallets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    return int(row[0]) if row else 0


def select_download(qq_user_id: str, group_id: str, index: int) -> Dict[str, Any]:
    user_id = get_or_create_user(qq_user_id)
    session = _get_active_session(user_id, str(group_id))
    if not session:
        return {
            "success": False,
            "error_code": "NO_ACTIVE_SESSION",
            "message": "未找到有效查询结果，请先 @机器人 发送资料编号或名称进行查询。",
        }

    target = None
    for item in session["results"]:
        if int(item.get("index", 0)) == int(index):
            target = item
            break
    if not target:
        return {
            "success": False,
            "error_code": "INVALID_INDEX",
            "message": f"编号 {index} 无效，请重新查询后再选择。",
        }

    document_id = int(target["document_id"])
    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    conn.isolation_level = None
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        if metadata_search_enabled():
            meta_doc = lookup_metadata_document(document_id)
            if not meta_doc:
                cur.execute("ROLLBACK")
                return {"success": False, "message": "资料不存在或已下架。"}
            doc = (
                document_id,
                meta_doc.get("code") or "",
                meta_doc.get("title") or "",
                meta_doc.get("category") or "",
                1,
            )
        else:
            cur.execute(
                """
                SELECT id, code, title, category, ticket_cost
                FROM documents
                WHERE id = ? AND is_active = 1 AND status = 'active'
                """,
                (document_id,),
            )
            doc = cur.fetchone()
            if not doc:
                cur.execute("ROLLBACK")
                return {"success": False, "message": "资料不存在或已下架。"}

        if metadata_search_enabled():
            share = resolve_metadata_share(document_id)
        else:
            share = _resolve_share_link(document_id)
        if not share.get("ok"):
            cur.execute("ROLLBACK")
            return {"success": False, "message": share.get("message")}

        balance = _get_wallet_balance(conn, user_id)
        ticket_cost = int(doc[4] or 1)
        free_mode = free_download_enabled()

        if not free_mode and balance < ticket_cost:
            cur.execute("ROLLBACK")
            return {
                "success": True,
                "need_pay": True,
                "message": "当前没有下载券",
                "ticket_cost": ticket_cost,
                "balance": balance,
            }

        now = _now()
        if free_mode:
            new_balance = balance
            log_ticket_cost = 0
            log_status = "free"
        else:
            cur.execute(
                "UPDATE ticket_wallets SET balance = balance - ?, updated_at = ? WHERE user_id = ?",
                (ticket_cost, now, user_id),
            )
            new_balance = balance - ticket_cost
            log_ticket_cost = ticket_cost
            log_status = "success"

        cur.execute(
            """
            INSERT INTO download_logs (
                user_id, group_id, document_id, pan_asset_id, share_link_id,
                ticket_cost, pan_share_url, pan_extract_code, status, created_at,
                doc_code, doc_title
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                str(group_id),
                document_id,
                share.get("pan_asset_id"),
                share.get("share_link_id"),
                log_ticket_cost,
                share["pan_share_url"],
                share["pan_extract_code"],
                log_status,
                now,
                doc[1],
                doc[2],
            ),
        )
        cur.execute("COMMIT")
        return {
            "success": True,
            "need_pay": False,
            "free_download": free_mode,
            "document": {
                "id": doc[0],
                "code": doc[1],
                "title": doc[2],
                "category": doc[3] or "",
            },
            "ticket_cost": 0 if free_mode else ticket_cost,
            "balance": new_balance,
            "pan_share_url": share["pan_share_url"],
            "pan_extract_code": share["pan_extract_code"],
        }
    except Exception as e:
        cur.execute("ROLLBACK")
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def create_ticket_order(qq_user_id: str, group_id: str, pack_code: str) -> Dict[str, Any]:
    pack = TICKET_PACKS.get(pack_code)
    if not pack:
        return {"success": False, "message": "无效套餐，请回复 买1 / 买10 / 买25。"}

    user_id = get_or_create_user(qq_user_id)
    order_no = f"T{int(_now())}{secrets.randbelow(1000):03d}"
    now = _now()
    expired_at = now + ORDER_EXPIRE_SECONDS

    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ticket_orders (
            order_no, user_id, group_id, pack_code, ticket_count, amount_cent,
            status, expired_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (
            order_no,
            user_id,
            str(group_id),
            pack_code,
            pack["ticket_count"],
            pack["amount_cent"],
            expired_at,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    from services.payment_service import create_alipay_pay

    amount_yuan = round(pack["amount_cent"] / 100.0, 2)
    pay_res = create_alipay_pay(
        subject=f"下载券-{pack['name']}",
        total_amount=amount_yuan,
        out_trade_no=order_no,
    )
    if pay_res.get("status") != "success":
        return {"success": False, "message": pay_res.get("message", "创建支付失败")}

    pay_url = pay_res["pay_url"]
    if pay_res.get("trade_method") == "precreate" and "qr.alipay.com" not in pay_url:
        return {
            "success": False,
            "message": pay_res.get("message") or "当面付二维码生成失败，请稍后重试",
        }
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    cur.execute(
        "UPDATE ticket_orders SET pay_url = ?, updated_at = ? WHERE order_no = ?",
        (pay_url, _now(), order_no),
    )
    conn.commit()
    conn.close()

    return {
        "success": True,
        "order_no": order_no,
        "pack_code": pack_code,
        "pack_name": pack["name"],
        "amount_cent": pack["amount_cent"],
        "ticket_count": pack["ticket_count"],
        "pay_url": pay_url,
        "expired_at": expired_at,
        "qq_user_id": str(qq_user_id),
        "group_id": str(group_id),
    }


def fulfill_ticket_order(order_no: str, alipay_trade_no: Optional[str] = None) -> Dict[str, Any]:
    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    conn.isolation_level = None
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            """
            SELECT id, user_id, group_id, ticket_count, amount_cent, status
            FROM ticket_orders WHERE order_no = ?
            """,
            (order_no,),
        )
        row = cur.fetchone()
        if not row:
            cur.execute("ROLLBACK")
            return {"status": "error", "message": "ticket order not found"}

        order_id, user_id, group_id, ticket_count, amount_cent, status = row
        if status == "paid":
            cur.execute("ROLLBACK")
            cur.execute("SELECT qq_user_id FROM lib_users WHERE id = ?", (user_id,))
            qq_row = cur.fetchone()
            cur.execute("SELECT balance FROM ticket_wallets WHERE user_id = ?", (user_id,))
            bal = cur.fetchone()
            return {
                "status": "success",
                "message": "already processed",
                "qq_user_id": qq_row[0] if qq_row else None,
                "group_id": group_id,
                "ticket_count": ticket_count,
                "balance": bal[0] if bal else 0,
            }

        if status != "pending":
            cur.execute("ROLLBACK")
            return {"status": "error", "message": f"invalid order status: {status}"}

        now = _now()
        cur.execute(
            """
            UPDATE ticket_orders
            SET status = 'paid', paid_at = ?, alipay_trade_no = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, alipay_trade_no, now, order_id),
        )
        cur.execute(
            """
            UPDATE ticket_wallets
            SET balance = balance + ?, updated_at = ?
            WHERE user_id = ?
            """,
            (ticket_count, now, user_id),
        )
        cur.execute("SELECT balance FROM ticket_wallets WHERE user_id = ?", (user_id,))
        balance = cur.fetchone()[0]
        cur.execute("SELECT qq_user_id FROM lib_users WHERE id = ?", (user_id,))
        qq_user_id = cur.fetchone()[0]
        cur.execute("COMMIT")
        return {
            "status": "success",
            "message": "ticket order paid",
            "qq_user_id": qq_user_id,
            "group_id": group_id,
            "ticket_count": ticket_count,
            "balance": balance,
            "amount_cent": amount_cent,
        }
    except Exception as e:
        cur.execute("ROLLBACK")
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def get_wallet_by_qq(qq_user_id: str) -> Dict[str, Any]:
    user_id = get_or_create_user(qq_user_id)
    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    cur.execute("SELECT balance FROM ticket_wallets WHERE user_id = ?", (user_id,))
    bal_row = cur.fetchone()
    balance = int(bal_row[0]) if bal_row else 0
    cur.execute(
        """
        SELECT COALESCE(dl.doc_code, d.code), COALESCE(dl.doc_title, d.title), dl.created_at
        FROM download_logs dl
        LEFT JOIN documents d ON d.id = dl.document_id
        WHERE dl.user_id = ? AND dl.status = 'success'
        ORDER BY dl.id DESC
        LIMIT 5
        """,
        (user_id,),
    )
    downloads = [
        {"code": r[0], "title": r[1], "downloaded_at": r[2]}
        for r in cur.fetchall()
    ]
    conn.close()
    return {"success": True, "balance": balance, "recent_downloads": downloads}


def resend_last_download(qq_user_id: str, group_id: str) -> Dict[str, Any]:
    user_id = get_or_create_user(qq_user_id)
    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT dl.document_id, dl.pan_share_url, dl.pan_extract_code, dl.created_at,
               COALESCE(dl.doc_code, d.code), COALESCE(dl.doc_title, d.title)
        FROM download_logs dl
        LEFT JOIN documents d ON d.id = dl.document_id
        WHERE dl.user_id = ? AND dl.status = 'success'
        ORDER BY dl.id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"success": False, "message": "没有可重发的下载记录。"}

    _, url, code, created_at, doc_code, title = row
    if _now() - float(created_at) > RESEND_WINDOW_SECONDS:
        return {
            "success": False,
            "message": "最近一次下载已超过 24 小时，请重新选择资料下载（将扣除下载券）。",
        }

    return {
        "success": True,
        "document": {"code": doc_code, "title": title},
        "pan_share_url": url,
        "pan_extract_code": code or "",
    }


def get_ticket_order_by_no(order_no: str) -> Optional[Dict[str, Any]]:
    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT o.order_no, o.amount_cent, o.status, u.qq_user_id, o.group_id, o.ticket_count
        FROM ticket_orders o
        JOIN lib_users u ON u.id = o.user_id
        WHERE o.order_no = ?
        """,
        (order_no,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "order_no": row[0],
        "amount_cent": row[1],
        "status": row[2],
        "qq_user_id": row[3],
        "group_id": row[4],
        "ticket_count": row[5],
    }
