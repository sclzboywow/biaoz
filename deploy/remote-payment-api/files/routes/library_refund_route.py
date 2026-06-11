"""Route appended to api/library.py"""

LIBRARY_REFUND_ROUTE = '''
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
