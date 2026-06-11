#!/usr/bin/env python3
from pathlib import Path

path = Path("/home/ubuntu/qq-ai-bot/app.py")
text = path.read_text(encoding="utf-8")
marker = '@app.post("/internal/send-group-msg")'
if marker in text:
    print("already patched")
    raise SystemExit(0)

needle = '@app.post("/internal/qq-file/send-private")'
insert = '''
@app.post("/internal/send-group-msg")
async def internal_send_group_msg(
    payload: Dict[str, Any],
    x_internal_secret: Optional[str] = Header(default=None, alias="X-Internal-Secret"),
):
    """Send plain text to a QQ group."""
    _require_internal_secret(x_internal_secret)
    group_id = payload.get("group_id")
    text = (payload.get("text") or payload.get("message") or "").strip()
    if not group_id or not text:
        raise HTTPException(status_code=400, detail="group_id and text are required")

    if _bot_ws and _bot_send_lock:
        await send_group_msg(_bot_ws, _bot_send_lock, group_id, text)
        return {"status": "ok", "via": "onebot_ws"}

    api = get_qq_file_api()
    data = await api.client.call_api("send_group_msg", {"group_id": int(group_id), "message": text})
    return {"status": "ok", "via": "napcat_http", "data": data}


'''
if needle not in text:
    raise SystemExit("anchor not found")
path.write_text(text.replace(needle, insert + needle, 1), encoding="utf-8")
print("patched app.py")
