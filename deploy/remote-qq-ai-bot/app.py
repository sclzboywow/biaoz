import asyncio

import json

import os

import subprocess

import uuid

from typing import Any, Dict, List, Optional



import httpx

import uvicorn

from dotenv import load_dotenv

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect



from ai.db import init_ai_db
from ai.templates import format_ticket_paid_notice, help_text_private
from bot_library import LibraryBotHandler, is_private_scope
from library_client import LibraryClient
from qq_file_api import extract_file_segments_from_event, get_qq_file_api



load_dotenv()
init_ai_db()



HOST = os.getenv("HOST", "127.0.0.1")

PORT = int(os.getenv("PORT", "8765"))



# 可选覆盖；未设置时以 NapCat 扫码登录账号（事件 self_id）为准
BOT_QQ = os.getenv("BOT_QQ", "").strip()
_bot_qq_cache: Optional[str] = None

GROUP_PREFIX = os.getenv("GROUP_PREFIX", "/ai")

LIBRARY_MODE = os.getenv("LIBRARY_MODE", "true").lower() == "true"

BOT_INTERNAL_SECRET = os.getenv("BOT_INTERNAL_SECRET", "").strip()



ALLOW_USERS = {x.strip() for x in os.getenv("ALLOW_USERS", "").split(",") if x.strip()}

ALLOW_GROUPS = {x.strip() for x in os.getenv("ALLOW_GROUPS", "").split(",") if x.strip()}

AUTO_ACCEPT_FRIEND = os.getenv("AUTO_ACCEPT_FRIEND", "true").lower() in {"1", "true", "yes", "on"}



LLM_MODE = os.getenv("LLM_MODE", "mock")

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "ollama")

MODEL = os.getenv("MODEL", "qwen2.5:7b")

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "你是一个简洁、直接、有帮助的QQ助手。")

MAX_REPLY_LENGTH = int(os.getenv("MAX_REPLY_LENGTH", "1000"))



app = FastAPI()

napcat_connected = False

_bot_ws: Optional[WebSocket] = None

_bot_send_lock: Optional[asyncio.Lock] = None

_ws_connection_id = 0

library_handler = LibraryBotHandler(LibraryClient())


def probe_napcat_qq_status() -> dict:
    try:
        recent = subprocess.check_output(
            ["docker", "logs", "--since", "15m", "napcat"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        return {"qq_login_status": "unknown", "qq_login_detail": str(exc)[:200]}

    if "请扫描下面的二维码" in recent or "用户身份已失效" in recent or "二维码已保存" in recent:
        status = "need_qr_login"
    elif "快速登录错误" in recent and "接收 <-" not in recent:
        status = "login_failed"
    elif "接收 <-" in recent or "发送 ->" in recent:
        status = "active"
    elif "正在快速登录" in recent:
        status = "logging_in"
    else:
        status = "unknown"

    qr_url = None
    for line in recent.splitlines():
        if line.strip().startswith("二维码解码URL:"):
            qr_url = line.split(":", 1)[1].strip()
            break

    return {
        "qq_login_status": status,
        "qq_login_detail": {
            "need_qr_login": "QQ 登录态失效，需手机扫码",
            "login_failed": "快速登录失败，需重新扫码",
            "active": "近期有收发消息",
            "logging_in": "正在登录",
            "unknown": "无法从 NapCat 日志判断",
        }.get(status, status),
        "qq_qr_url": qr_url,
    }


def message_to_text(message: Any) -> str:

    if isinstance(message, str):

        return message.strip()



    if isinstance(message, list):

        parts = []

        for seg in message:

            if not isinstance(seg, dict):

                continue



            seg_type = seg.get("type")

            data = seg.get("data", {})



            if seg_type == "text":

                parts.append(data.get("text", ""))

            elif seg_type == "at":

                parts.append(f"@{data.get('qq', '')}")



        return "".join(parts).strip()



    return ""





def bot_qq_for(event: Optional[Dict[str, Any]] = None) -> str:
    global _bot_qq_cache
    if event and event.get("self_id"):
        _bot_qq_cache = str(event["self_id"])
    if BOT_QQ:
        return BOT_QQ
    return _bot_qq_cache or ""


def has_at_bot(message: Any, bot_qq: str) -> bool:
    if not bot_qq:
        return False
    if not isinstance(message, list):
        return False
    for seg in message:
        if not isinstance(seg, dict):
            continue
        if seg.get("type") == "at":
            qq = str(seg.get("data", {}).get("qq", ""))
            if qq == bot_qq:
                return True
    return False





def is_allowed_user(user_id: Any) -> bool:

    if not ALLOW_USERS:

        return True

    return str(user_id) in ALLOW_USERS





def is_allowed_group(group_id: Any) -> bool:

    if not ALLOW_GROUPS:

        return True

    return str(group_id) in ALLOW_GROUPS





def extract_query(event: Dict[str, Any]) -> Optional[str]:

    message_type = event.get("message_type")

    user_id = event.get("user_id")

    group_id = event.get("group_id")

    self_id = event.get("self_id")



    if str(user_id) == str(self_id):

        return None



    raw_message = event.get("message", "")

    text = message_to_text(raw_message)



    if not text:

        return None



    if message_type == "private":

        if not is_allowed_user(user_id):

            return None

        return text



    if message_type == "group":

        if not is_allowed_group(group_id):

            return None



        if GROUP_PREFIX and text.startswith(GROUP_PREFIX):

            return text[len(GROUP_PREFIX) :].strip()



        bot_qq = bot_qq_for(event)
        if has_at_bot(raw_message, bot_qq):

            cleaned = text.replace(f"@{bot_qq}", "").strip()

            return cleaned or "你好"



    return None





async def ask_llm(prompt: str) -> str:

    if LLM_MODE == "mock":

        return f"收到：{prompt}"



    url = f"{OPENAI_BASE_URL}/chat/completions"



    payload = {

        "model": MODEL,

        "messages": [

            {"role": "system", "content": SYSTEM_PROMPT},

            {"role": "user", "content": prompt},

        ],

        "temperature": 0.7,

    }



    headers = {

        "Authorization": f"Bearer {OPENAI_API_KEY}",

        "Content-Type": "application/json",

    }



    try:

        async with httpx.AsyncClient(timeout=60) as client:

            resp = await client.post(url, headers=headers, json=payload)

            resp.raise_for_status()

            data = resp.json()

            reply = data["choices"][0]["message"]["content"].strip()

            return reply[:MAX_REPLY_LENGTH]

    except Exception as e:

        return f"AI接口调用失败：{type(e).__name__}"





async def send_api_action(ws: WebSocket, send_lock: asyncio.Lock, action: str, params: Dict[str, Any]):
    payload = {
        "action": action,
        "params": params,
        "echo": str(uuid.uuid4()),
    }
    try:
        async with send_lock:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        print(f"[send] {action} failed: {type(e).__name__}: {e}", flush=True)
        raise


async def send_private_msg(ws: WebSocket, send_lock: asyncio.Lock, user_id: Any, message: Any):
    await send_api_action(
        ws,
        send_lock,
        "send_private_msg",
        {"user_id": user_id, "message": message},
    )





async def send_group_msg(

    ws: WebSocket,

    send_lock: asyncio.Lock,

    group_id: Any,

    message: Any,

):

    await send_api_action(
        ws,
        send_lock,
        "send_group_msg",
        {"group_id": group_id, "message": message},
    )


def _require_internal_secret(x_internal_secret: Optional[str]) -> None:
    if BOT_INTERNAL_SECRET and x_internal_secret != BOT_INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")


def library_event_allowed(event: Dict[str, Any]) -> bool:
    message_type = event.get("message_type")
    if message_type == "group":
        return is_allowed_group(event.get("group_id"))
    if message_type == "private":
        return is_allowed_user(event.get("user_id"))
    return False


async def send_library_reply(
    ws: WebSocket,
    send_lock: asyncio.Lock,
    event: Dict[str, Any],
    text: str,
    extra_segments: Optional[List[Dict[str, Any]]] = None,
):
    message: Any
    if extra_segments:
        message = [{"type": "text", "data": {"text": text}}] + extra_segments
    else:
        message = text

    if event.get("message_type") == "private":
        await send_private_msg(ws, send_lock, event.get("user_id"), message)
    else:
        await send_group_msg(ws, send_lock, event.get("group_id"), message)


async def handle_request_event(ws: WebSocket, send_lock: asyncio.Lock, event: Dict[str, Any]):
    if event.get("post_type") != "request":
        return

    request_type = event.get("request_type")
    if request_type == "friend" and AUTO_ACCEPT_FRIEND:
        flag = event.get("flag")
        if not flag:
            return
        user_id = event.get("user_id")
        comment = (event.get("comment") or "").strip()
        print(f"自动通过好友请求 user_id={user_id} comment={comment!r}")
        await send_api_action(
            ws,
            send_lock,
            "set_friend_add_request",
            {"flag": flag, "approve": True, "remark": ""},
        )
        try:
            welcome = (
                "好友已通过，私聊标准库已开通。\n\n"
                "直接发送标准号或名称即可查询，例如：GB50016\n"
                "发送「帮助」查看完整用法。"
            )
            await send_private_msg(ws, send_lock, user_id, welcome)
        except Exception as e:
            print(f"发送私聊欢迎语失败 user_id={user_id}: {type(e).__name__}: {e}")
        return

    if request_type == "group" and os.getenv("AUTO_ACCEPT_GROUP", "false").lower() in {"1", "true", "yes", "on"}:
        flag = event.get("flag")
        if not flag:
            return
        sub_type = event.get("sub_type")
        approve = sub_type != "invite"
        print(f"自动处理加群请求 sub_type={sub_type} approve={approve}")
        await send_api_action(
            ws,
            send_lock,
            "set_group_add_request",
            {"flag": flag, "approve": approve, "reason": ""},
        )


async def handle_event(ws: WebSocket, send_lock: asyncio.Lock, event: Dict[str, Any]):
    post_type = event.get("post_type")
    if post_type == "request":
        await handle_request_event(ws, send_lock, event)
        return

    if post_type != "message":
        return

    message_type = event.get("message_type")
    preview = message_to_text(event.get("message", ""))
    file_segments = extract_file_segments_from_event(event)
    print(
        f"[msg] type={message_type} user={event.get('user_id')} "
        f"group={event.get('group_id')} text={preview[:80]!r}",
        flush=True,
    )
    if file_segments:
        for seg in file_segments:
            print(
                f"[file] user={event.get('user_id')} group={event.get('group_id')} "
                f"name={seg.file_name!r} size={seg.file_size} file_id={seg.file_id!r}",
                flush=True,
            )

    is_private = message_type == "private"

    if LIBRARY_MODE and library_event_allowed(event):
        try:
            handled = await library_handler.handle(event, bot_qq_for(event))
            if handled is not None:
                text, extra_segments = handled
                await send_library_reply(ws, send_lock, event, text, extra_segments)
                return
            if is_private and message_to_text(event.get("message", "")):
                await send_private_msg(
                    ws, send_lock, event.get("user_id"), help_text_private()
                )
                return
        except Exception as e:
            print(f"[library] 处理失败 user_id={event.get('user_id')}: {type(e).__name__}: {e}")
            err = "标准库处理失败，请稍后重试。发送「帮助」查看用法。"
            await send_library_reply(ws, send_lock, event, err, None)
            return

    if is_private and LIBRARY_MODE:
        return

    query = extract_query(event)
    if not query:
        return

    reply = await ask_llm(query)

    if is_private:
        await send_private_msg(ws, send_lock, event.get("user_id"), reply)
    elif message_type == "group":
        await send_group_msg(ws, send_lock, event.get("group_id"), reply)


async def safe_handle_event(ws: WebSocket, send_lock: asyncio.Lock, event: Dict[str, Any]):
    try:
        await handle_event(ws, send_lock, event)
    except Exception as e:
        print(f"[handle_event] 未捕获异常: {type(e).__name__}: {e}")





@app.post("/internal/ticket-paid")

async def internal_ticket_paid(

    payload: Dict[str, Any],

    x_internal_secret: Optional[str] = Header(default=None, alias="X-Internal-Secret"),

):

    _require_internal_secret(x_internal_secret)

    group_id = payload.get("group_id")
    user_id = payload.get("user_id")

    if not group_id or not _bot_ws or not _bot_send_lock:
        return {"status": "ok", "delivered": False}

    text = format_ticket_paid_notice(payload)

    if is_private_scope(group_id):
        target_user = user_id or str(group_id).removeprefix("private:")
        await send_private_msg(_bot_ws, _bot_send_lock, target_user, text)
    else:
        await send_group_msg(_bot_ws, _bot_send_lock, group_id, text)

    return {"status": "ok", "delivered": True}


@app.post("/internal/qq-file/send-group")
async def internal_qq_file_send_group(
    payload: Dict[str, Any],
    x_internal_secret: Optional[str] = Header(default=None, alias="X-Internal-Secret"),
):
    """
    向群聊天窗口发送文件（不走群文件盘，用户可见）。
    payload: { group_id, file_path, intro_text?, file_name? }
    """
    _require_internal_secret(x_internal_secret)
    group_id = payload.get("group_id")
    file_path = (payload.get("file_path") or "").strip()
    if not group_id or not file_path:
        raise HTTPException(status_code=400, detail="group_id and file_path are required")

    api = get_qq_file_api()
    result = await api.send_group_file(
        group_id=group_id,
        file_path=file_path,
        intro_text=(payload.get("intro_text") or None),
        mode="chat",
        file_name=(payload.get("file_name") or None),
    )
    from cache_cleanup import cleanup_local_cache

    cleanup = cleanup_local_cache()
    return {"status": "ok", "result": result.to_dict(), "cache_cleanup": cleanup}


@app.post("/internal/send-group-msg")
async def internal_send_group_msg(
    payload: Dict[str, Any],
    x_internal_secret: Optional[str] = Header(default=None, alias="X-Internal-Secret"),
):
    """向群发送文本消息。payload: { group_id, text | message }"""
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


@app.post("/internal/qq-file/send-private")
async def internal_qq_file_send_private(
    payload: Dict[str, Any],
    x_internal_secret: Optional[str] = Header(default=None, alias="X-Internal-Secret"),
):
    """
    向私聊发送文件（upload_private_file）。
    payload: { user_id, file_path, intro_text?, file_name? }
    """
    _require_internal_secret(x_internal_secret)
    user_id = payload.get("user_id")
    file_path = (payload.get("file_path") or "").strip()
    if not user_id or not file_path:
        raise HTTPException(status_code=400, detail="user_id and file_path are required")

    api = get_qq_file_api()
    result = await api.send_private_file(
        user_id=user_id,
        file_path=file_path,
        intro_text=(payload.get("intro_text") or None),
        file_name=(payload.get("file_name") or None),
    )
    return {"status": "ok", "result": result.to_dict()}


@app.post("/internal/qq-file/download")
async def internal_qq_file_download(
    payload: Dict[str, Any],
    x_internal_secret: Optional[str] = Header(default=None, alias="X-Internal-Secret"),
):
    """
    下载群/私聊文件到服务器本地。
    payload 二选一：
      - { message_id, group_id?, save_dir?, segment_index? }
      - { event, save_dir?, segment_index? }  # 完整 OneBot 消息事件
    """
    _require_internal_secret(x_internal_secret)
    api = get_qq_file_api()
    save_dir = payload.get("save_dir")
    segment_index = int(payload.get("segment_index") or 0)

    if payload.get("event"):
        downloaded = await api.download_from_event(
            payload["event"],
            save_dir=save_dir,
            segment_index=segment_index,
        )
    elif payload.get("message_id"):
        downloaded = await api.download_from_message_id(
            payload["message_id"],
            group_id=payload.get("group_id"),
            save_dir=save_dir,
            segment_index=segment_index,
        )
    else:
        raise HTTPException(status_code=400, detail="event or message_id is required")

    return {"status": "ok", "file": downloaded.to_dict()}


@app.get("/internal/qq-file/health")
async def internal_qq_file_health(
    x_internal_secret: Optional[str] = Header(default=None, alias="X-Internal-Secret"),
):
    _require_internal_secret(x_internal_secret)
    api = get_qq_file_api()
    ok = await api.client.ping()
    return {
        "status": "ok",
        "napcat_http_ok": ok,
        "napcat_http_url": api.client.base_url,
        "staging_dir": str(api.staging_dir),
        "download_dir": str(api.download_dir),
    }


@app.post("/internal/qq-file/parse-message")
async def internal_qq_file_parse_message(
    payload: Dict[str, Any],
    x_internal_secret: Optional[str] = Header(default=None, alias="X-Internal-Secret"),
):
    """解析消息中的 file 段。payload: { message } 或 { event }"""
    _require_internal_secret(x_internal_secret)
    if payload.get("event"):
        segments = extract_file_segments_from_event(payload["event"])
    else:
        from qq_file_api import extract_file_segments

        segments = extract_file_segments(payload.get("message"))
    return {"status": "ok", "segments": [s.to_dict() for s in segments]}





@app.get("/")

@app.get("/health")

async def health():

    return {

        "status": "ok",

        "service": "qq-ai-bot",

        "host": HOST,

        "port": PORT,

        "llm_mode": LLM_MODE,

        "library_mode": LIBRARY_MODE,

        "private_library_mode": LIBRARY_MODE,

        "auto_accept_friend": AUTO_ACCEPT_FRIEND,

        "ai_mode": os.getenv("AI_MODE", "light"),

        "deepseek_configured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),

        "napcat_connected": napcat_connected,
        "napcat_ws_ok": napcat_connected,
        **probe_napcat_qq_status(),

        "bot_qq": bot_qq_for() or None,

        "bot_qq_source": "env" if BOT_QQ else ("napcat" if _bot_qq_cache else None),

        "websocket_path": "/onebot/v11/ws",

        "hint": "napcat_connected 仅表示 OneBot WebSocket；qq_login_status=active 才表示 QQ 真正能收发消息",
        "qq_file_api": {
            "enabled": True,
            "napcat_http_url": get_qq_file_api().client.base_url,
            "endpoints": [
                "/internal/qq-file/health",
                "/internal/qq-file/send-group",
                "/internal/qq-file/send-private",
                "/internal/qq-file/download",
                "/internal/qq-file/parse-message",
            ],
        },

    }





@app.websocket("/onebot/v11/ws")

async def onebot_ws(ws: WebSocket):

    global napcat_connected, _bot_ws, _bot_send_lock, _ws_connection_id

    await ws.accept()

    send_lock = asyncio.Lock()

    _ws_connection_id += 1
    conn_id = _ws_connection_id

    napcat_connected = True

    _bot_ws = ws

    _bot_send_lock = send_lock



    print(f"NapCatQQ WebSocket 已连接 conn_id={conn_id}")



    try:

        while True:

            raw = await ws.receive_text()



            try:

                data = json.loads(raw)

            except json.JSONDecodeError:

                print("收到非 JSON 消息：", raw)

                continue



            if "post_type" not in data:

                continue



            asyncio.create_task(safe_handle_event(ws, send_lock, data))



    except WebSocketDisconnect:

        if conn_id == _ws_connection_id:
            napcat_connected = False

            _bot_ws = None

            _bot_send_lock = None

        print(f"NapCatQQ WebSocket 已断开 conn_id={conn_id}")





if __name__ == "__main__":

    uvicorn.run(app, host=HOST, port=PORT)


