#!/usr/bin/env python3
from pathlib import Path

# Fix payments.py - remove broken tail and append ASCII routes
pay_path = Path("/home/ubuntu/payment-api/api/payments.py")
ptext = pay_path.read_text(encoding="utf-8", errors="replace")
if "@router.post(\"/alipay/refund\")" in ptext:
    ptext = ptext.split("@router.post(\"/alipay/refund\")")[0].rstrip() + "\n"
if "refund_alipay_trade" not in ptext:
    ptext = ptext.replace(
        "from services.payment_service import query_alipay_trade, process_alipay_async_notify",
        "from services.payment_service import query_alipay_trade, process_alipay_async_notify, refund_alipay_trade, query_alipay_refund",
    )

pay_addon = '''
@router.post("/alipay/refund")
async def api_alipay_refund(payload: Dict[str, Any], x_internal_secret: str = Header(default=None, alias="X-Internal-Secret")):
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
        refund_reason=str(payload.get("reason") or "refund"),
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
if "api_alipay_refund" not in ptext:
    if "Header" not in ptext.split("from fastapi")[1][:200]:
        ptext = ptext.replace(
            "from fastapi import APIRouter, Query, Header, Depends, HTTPException, Request",
            "from fastapi import APIRouter, Query, Header, Depends, HTTPException, Request",
        )
    ptext = ptext.rstrip() + pay_addon + "\n"
pay_path.write_text(ptext, encoding="utf-8")
print("fixed payments.py")

# Fix library.py
lib_path = Path("/home/ubuntu/payment-api/api/library.py")
ltext = lib_path.read_text(encoding="utf-8", errors="replace")
if "@router.post(\"/api/internal/ticket-order/refund\")" in ltext:
    ltext = ltext.split("@router.post(\"/api/internal/ticket-order/refund\")")[0].rstrip() + "\n"
if "from library.refund import refund_ticket_order" not in ltext:
    ltext = ltext.replace(
        "from fastapi import APIRouter, Query, Request",
        "from fastapi import APIRouter, Query, Request, Header, HTTPException",
    )
    ltext = ltext.replace(
        "from library.constants import TICKET_PACKS",
        "import os\nfrom library.constants import TICKET_PACKS\nfrom library.refund import refund_ticket_order",
    )
lib_addon = '''
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
        reason=str(payload.get("reason") or "admin refund"),
        operator=str(payload.get("operator") or "admin"),
        refund_amount_yuan=payload.get("refund_amount_yuan"),
    )
    code = 200 if result.get("status") == "success" else 400
    return JSONResponse(result, status_code=code)
'''
if "api_internal_ticket_refund" not in ltext:
    ltext = ltext.rstrip() + lib_addon + "\n"
lib_path.write_text(ltext, encoding="utf-8")
print("fixed library.py")
