"""Routes appended to api/payments.py"""

PAYMENTS_REFUND_ROUTES = '''
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
