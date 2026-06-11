#!/bin/bash
set -euo pipefail
ROOT="/home/ubuntu/payment-api"
cd "$ROOT"

# 1) payment_service refund APIs
python3 <<'PY'
from pathlib import Path
import textwrap

path = Path("services/payment_service.py")
text = path.read_text(encoding="utf-8")
marker = "def refund_alipay_trade("
if marker in text:
    print("payment_service refund already present")
else:
    addon = textwrap.dedent('''


def refund_alipay_trade(
    *,
    out_trade_no: str,
    refund_amount: float,
    out_request_no: str,
    trade_no=None,
    refund_reason: str = "用户申请退款",
):
    """当面付/扫码支付退款（alipay.trade.refund）。"""
    try:
        cfg = load_platform_payment_config('alipay') or {}
        private_key = (cfg.get('private_key') or '').strip()
        if not private_key:
            return {"status": "error", "message": "missing private key"}

        gateway = os.getenv('ALIPAY_GATEWAY') or 'https://openapi.alipay.com/gateway.do'
        params = _alipay_common_fields('alipay.trade.refund')
        biz_content = {
            'out_trade_no': out_trade_no,
            'refund_amount': f"{round(float(refund_amount), 2):.2f}",
            'out_request_no': out_request_no,
        }
        if trade_no:
            biz_content['trade_no'] = trade_no
        if refund_reason:
            biz_content['refund_reason'] = refund_reason
        params['biz_content'] = json.dumps(biz_content, ensure_ascii=False, separators=(',', ':'))
        params = _sign_alipay_params(params, private_key)

        resp = _alipay_post(params, gateway)
        if not resp.ok:
            return {"status": "error", "message": resp.text}
        data = resp.json()
        body = data.get('alipay_trade_refund_response') or {}
        code = str(body.get('code') or '')
        if code != '10000':
            return {
                "status": "error",
                "message": body.get('sub_msg') or body.get('msg') or 'refund failed',
                "raw": body,
                "out_request_no": out_request_no,
            }
        return {
            "status": "success",
            "fund_change": body.get('fund_change'),
            "refund_fee": body.get('refund_fee'),
            "trade_no": body.get('trade_no'),
            "out_trade_no": body.get('out_trade_no') or out_trade_no,
            "out_request_no": out_request_no,
            "raw": body,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "out_request_no": out_request_no}


def query_alipay_refund(out_request_no: str, *, out_trade_no=None, trade_no=None):
    """查询退款结果（alipay.trade.fastpay.refund.query）。"""
    try:
        cfg = load_platform_payment_config('alipay') or {}
        private_key = (cfg.get('private_key') or '').strip()
        if not private_key:
            return {"status": "error", "message": "missing private key"}

        gateway = os.getenv('ALIPAY_GATEWAY') or 'https://openapi.alipay.com/gateway.do'
        params = _alipay_common_fields('alipay.trade.fastpay.refund.query')
        biz_content = {'out_request_no': out_request_no}
        if out_trade_no:
            biz_content['out_trade_no'] = out_trade_no
        if trade_no:
            biz_content['trade_no'] = trade_no
        params['biz_content'] = json.dumps(biz_content, ensure_ascii=False, separators=(',', ':'))
        params = _sign_alipay_params(params, private_key)

        resp = _alipay_post(params, gateway)
        if not resp.ok:
            return {"status": "error", "message": resp.text}
        data = resp.json()
        body = data.get('alipay_trade_fastpay_refund_query_response') or {}
        code = str(body.get('code') or '')
        return {
            "status": "success" if code == '10000' else "error",
            "refund_status": body.get('refund_status'),
            "raw": body,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
''')
    path.write_text(text.rstrip() + addon, encoding="utf-8")
    print("payment_service refund appended")
PY

# 2) ticket_orders refund columns
"$ROOT/.venv/bin/python" <<'PY'
import sqlite3
conn = sqlite3.connect("/home/ubuntu/payment-api/library.db")
cols = {r[1] for r in conn.execute("PRAGMA table_info(ticket_orders)")}
for name, ddl in [
    ("refund_reason", "ALTER TABLE ticket_orders ADD COLUMN refund_reason TEXT"),
    ("refund_request_no", "ALTER TABLE ticket_orders ADD COLUMN refund_request_no TEXT"),
]:
    if name not in cols:
        conn.execute(ddl)
        print("added column", name)
conn.commit()
conn.close()
PY

# 3) library refund module
cat > library/refund.py <<'EOF'
"""下载券订单退款。"""
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
    order_no = (order_no or "").strip()
    if not order_no:
        return {"status": "error", "message": "missing order_no"}

    init_library_db()
    conn = sqlite3.connect(get_library_db_path())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, group_id, ticket_count, amount_cent, status, alipay_trade_no
        FROM ticket_orders WHERE order_no = ?
        """,
        (order_no,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"status": "error", "message": "ticket order not found"}

    order_id, user_id, group_id, ticket_count, amount_cent, status, alipay_trade_no = row
    if status == "refunded":
        return {"status": "success", "message": "already refunded", "order_no": order_no}
    if status != "paid":
        return {"status": "error", "message": f"order not refundable, status={status}"}

    amount_yuan = refund_amount_yuan if refund_amount_yuan is not None else round(int(amount_cent) / 100.0, 2)
    if amount_yuan <= 0:
        return {"status": "error", "message": "invalid refund amount"}

    out_request_no = f"RF{order_no}{secrets.randbelow(1000):03d}"
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
        cur.execute("SELECT status, ticket_count, user_id FROM ticket_orders WHERE order_no = ?", (order_no,))
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
EOF

# 4) API routes patch
python3 <<'PY'
from pathlib import Path

lib_api = Path("api/library.py")
text = lib_api.read_text(encoding="utf-8")
if "api_internal_ticket_refund" in text:
    print("library api refund route already present")
else:
    if "from fastapi import APIRouter, Query, Request" in text:
        text = text.replace(
            "from fastapi import APIRouter, Query, Request",
            "from fastapi import APIRouter, Query, Request, Header, HTTPException",
        )
    if "from library.refund import refund_ticket_order" not in text:
        insert = "\nfrom library.refund import refund_ticket_order\nimport os\n"
        text = text.replace("from library.service import (", insert + "from library.service import (")
    route = '''

@router.post("/api/internal/ticket-order/refund")
async def api_internal_ticket_refund(
    payload: Dict[str, Any],
    x_internal_secret: str = Header(default=None, alias="X-Internal-Secret"),
):
    expected = (os.getenv("BOT_INTERNAL_SECRET") or "").strip()
    if expected and x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="forbidden")
    order_no = str(payload.get("order_no") or "")
    if not order_no:
        return JSONResponse({"status": "error", "message": "missing order_no"}, status_code=400)
    result = refund_ticket_order(
        order_no,
        reason=str(payload.get("reason") or "管理员退款"),
        operator=str(payload.get("operator") or "admin"),
        refund_amount_yuan=payload.get("refund_amount_yuan"),
    )
    code = 200 if result.get("status") == "success" else 400
    return JSONResponse(result, status_code=code)
'''
    text = text.rstrip() + route + "\n"
    lib_api.write_text(text, encoding="utf-8")
    print("library api refund route added")

pay_api = Path("api/payments.py")
ptext = pay_api.read_text(encoding="utf-8")
if "api_alipay_refund" in ptext:
    print("payments api refund route already present")
else:
    if "from services.payment_service import query_alipay_trade, process_alipay_async_notify" in ptext:
        ptext = ptext.replace(
            "from services.payment_service import query_alipay_trade, process_alipay_async_notify",
            "from services.payment_service import query_alipay_trade, process_alipay_async_notify, refund_alipay_trade, query_alipay_refund",
        )
    route = '''

@router.post("/alipay/refund")
async def api_alipay_refund(payload: Dict[str, Any], x_internal_secret: str = Header(default=None, alias="X-Internal-Secret")):
    """当面付退款：需 X-Internal-Secret 或管理员权限。"""
    import os
    expected = (os.getenv("BOT_INTERNAL_SECRET") or "").strip()
    if expected and x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="forbidden")
    out_trade_no = str(payload.get("out_trade_no") or payload.get("order_no") or "").strip()
    if not out_trade_no:
        return JSONResponse({"status": "error", "message": "missing out_trade_no"}, status_code=400)
    amount = payload.get("refund_amount")
    if amount is None:
        amount_cents = payload.get("refund_amount_cents")
        amount = round(float(amount_cents) / 100.0, 2) if amount_cents is not None else None
    if amount is None:
        return JSONResponse({"status": "error", "message": "missing refund_amount"}, status_code=400)
    out_request_no = str(payload.get("out_request_no") or f"RF{out_trade_no}")
    result = refund_alipay_trade(
        out_trade_no=out_trade_no,
        refund_amount=float(amount),
        out_request_no=out_request_no,
        trade_no=payload.get("trade_no"),
        refund_reason=str(payload.get("reason") or "用户申请退款"),
    )
    code = 200 if result.get("status") == "success" else 400
    return JSONResponse(result, status_code=code)


@router.get("/alipay/refund/query")
async def api_alipay_refund_query(
    out_request_no: str,
    out_trade_no: Optional[str] = None,
    trade_no: Optional[str] = None,
    x_internal_secret: str = Header(default=None, alias="X-Internal-Secret"),
):
    import os
    expected = (os.getenv("BOT_INTERNAL_SECRET") or "").strip()
    if expected and x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="forbidden")
    result = query_alipay_refund(out_request_no, out_trade_no=out_trade_no, trade_no=trade_no)
    code = 200 if result.get("status") == "success" else 400
    return JSONResponse(result, status_code=code)
'''
    ptext = ptext.rstrip() + route + "\n"
    pay_api.write_text(ptext, encoding="utf-8")
    print("payments api refund routes added")
PY

sudo systemctl restart payment-api.service
sleep 2
systemctl is-active payment-api.service
echo deploy_refund_api_done
