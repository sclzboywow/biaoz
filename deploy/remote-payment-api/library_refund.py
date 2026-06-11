"""下载券订单退款：调用支付宝退款并回滚券余额。"""

from __future__ import annotations

import secrets
import sqlite3
import time
from typing import Any, Dict, Optional

from library.db import get_library_db_path, init_library_db


def _now() -> float:
    return time.time()


def refund_ticket_order(
    order_no: str,
    *,
    reason: str = "管理员退款",
    operator: str = "admin",
    refund_amount_yuan: Optional[float] = None,
) -> Dict[str, Any]:
    """对已支付的下载券订单发起支付宝退款，并扣回已发放的下载券。"""
    order_no = (order_no or "").strip()
    if not order_no:
        return {"status": "error", "message": "missing order_no"}

    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    conn.isolation_level = None
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            """
            SELECT id, user_id, group_id, ticket_count, amount_cent, status, alipay_trade_no
            FROM ticket_orders WHERE order_no = ?
            """,
            (order_no,),
        )
        row = cur.fetchone()
        if not row:
            cur.execute("ROLLBACK")
            return {"status": "error", "message": "ticket order not found"}

        order_id, user_id, group_id, ticket_count, amount_cent, status, alipay_trade_no = row
        if status == "refunded":
            cur.execute("ROLLBACK")
            return {"status": "success", "message": "already refunded", "order_no": order_no}
        if status != "paid":
            cur.execute("ROLLBACK")
            return {"status": "error", "message": f"order not refundable, status={status}"}

        amount_yuan = refund_amount_yuan
        if amount_yuan is None:
            amount_yuan = round(int(amount_cent) / 100.0, 2)
        if amount_yuan <= 0:
            cur.execute("ROLLBACK")
            return {"status": "error", "message": "invalid refund amount"}

        out_request_no = f"RF{order_no}{secrets.randbelow(1000):03d}"
        cur.execute("ROLLBACK")
    finally:
        conn.close()

    from services.payment_service import refund_alipay_trade

    pay_result = refund_alipay_trade(
        out_trade_no=order_no,
        refund_amount=amount_yuan,
        out_request_no=out_request_no,
        trade_no=alipay_trade_no,
        refund_reason=reason or "用户申请退款",
    )
    if pay_result.get("status") != "success":
        return {
            "status": "error",
            "message": pay_result.get("message") or "alipay refund failed",
            "alipay": pay_result,
            "order_no": order_no,
        }

    conn = sqlite3.connect(get_library_db_path())
    conn.isolation_level = None
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT status, ticket_count, user_id FROM ticket_orders WHERE order_no = ?",
            (order_no,),
        )
        row = cur.fetchone()
        if not row or row[0] != "paid":
            cur.execute("ROLLBACK")
            return {"status": "error", "message": "order status changed during refund"}

        _, ticket_count, user_id = row
        now = _now()
        cur.execute(
            """
            UPDATE ticket_orders
            SET status = 'refunded', updated_at = ?, refund_reason = ?, refund_request_no = ?
            WHERE order_no = ? AND status = 'paid'
            """,
            (now, reason, out_request_no, order_no),
        )
        if cur.rowcount != 1:
            cur.execute("ROLLBACK")
            return {"status": "error", "message": "failed to mark order refunded"}

        cur.execute("SELECT balance FROM ticket_wallets WHERE user_id = ?", (user_id,))
        bal_row = cur.fetchone()
        balance = int(bal_row[0]) if bal_row else 0
        deduct = min(balance, int(ticket_count))
        new_balance = max(0, balance - deduct)
        cur.execute(
            "UPDATE ticket_wallets SET balance = ?, updated_at = ? WHERE user_id = ?",
            (new_balance, now, user_id),
        )
        cur.execute("SELECT qq_user_id FROM lib_users WHERE id = ?", (user_id,))
        qq_row = cur.fetchone()
        cur.execute("COMMIT")
        return {
            "status": "success",
            "message": "refund completed",
            "order_no": order_no,
            "out_request_no": out_request_no,
            "refund_amount_yuan": amount_yuan,
            "tickets_deducted": deduct,
            "balance_after": new_balance,
            "qq_user_id": qq_row[0] if qq_row else None,
            "group_id": group_id,
            "operator": operator,
            "alipay": pay_result,
        }
    except Exception as e:
        cur.execute("ROLLBACK")
        return {"status": "error", "message": str(e), "order_no": order_no, "alipay": pay_result}
    finally:
        conn.close()
