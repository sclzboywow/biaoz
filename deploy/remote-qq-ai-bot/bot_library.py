import base64
import io
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import qrcode

from ai.service import AIService, extract_document_keyword, is_likely_search_query, is_smalltalk_only, local_intent_parse
from ai.templates import (
    help_text,
    help_text_private,
    tag_ai_reply,
    format_download_success,
    format_need_pay,
    format_order_created,
    format_resend,
    format_search_results,
    format_wallet,
)
from library_client import LibraryClient

BUY_PATTERN = re.compile(r"^(?:购买|买)\s*(1|10|25)$")
INDEX_PATTERN = re.compile(r"^([1-9]|10)$")
BALANCE_WORDS = {"余额", "我的", "下载券", "券"}
RESEND_WORDS = {"重发"}
HELP_WORDS = {"帮助", "怎么用", "使用说明"}

PACK_MAP = {
    "1": "ticket_1",
    "10": "ticket_10",
    "25": "ticket_25",
}

PRIVATE_SCOPE_PREFIX = "private:"


def private_scope_id(user_id: Any) -> str:
    return f"{PRIVATE_SCOPE_PREFIX}{user_id}"


def is_private_scope(scope_id: Any) -> bool:
    return str(scope_id or "").startswith(PRIVATE_SCOPE_PREFIX)


def strip_group_prefix(text: str) -> str:
    prefix = os.getenv("GROUP_PREFIX", "/ai")
    value = (text or "").strip()
    if prefix and value.startswith(prefix):
        return value[len(prefix) :].strip()
    return value


def extract_at_query(message: Any, bot_qq: str) -> Optional[str]:
    if not isinstance(message, list):
        text = str(message or "").strip()
        if not text:
            return None
        text = re.sub(rf"@{re.escape(bot_qq)}", "", text, flags=re.I).strip()
        return text or None

    has_at = False
    parts: List[str] = []
    for seg in message:
        if not isinstance(seg, dict):
            continue
        if seg.get("type") == "at":
            qq = str(seg.get("data", {}).get("qq", ""))
            if qq == str(bot_qq):
                has_at = True
        elif seg.get("type") == "text":
            parts.append(seg.get("data", {}).get("text", ""))

    if not has_at:
        return None

    query = "".join(parts).strip()
    query = re.sub(r"^[@\s\u2005\u00a0]+", "", query).strip()
    return query or None


def has_at_bot(message: Any, bot_qq: str) -> bool:
    if not isinstance(message, list):
        return f"@{bot_qq}" in str(message or "")
    for seg in message:
        if isinstance(seg, dict) and seg.get("type") == "at":
            if str(seg.get("data", {}).get("qq", "")) == str(bot_qq):
                return True
    return False


def is_flow_message(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t in HELP_WORDS or t in BALANCE_WORDS or t in RESEND_WORDS:
        return True
    if BUY_PATTERN.match(t):
        return True
    if INDEX_PATTERN.fullmatch(t):
        return True
    return False


def is_direct_search_query(query: str) -> bool:
    if extract_document_keyword(query):
        return True
    if is_smalltalk_only(query):
        return False
    if re.search(r"(帮|有没有|怎么|笑话|你是谁|你会|下载|选择|余额|重发|买)", query):
        return False
    return is_likely_search_query(query)


def make_qr_image_segment(pay_url: str) -> Dict[str, Any]:
    img = qrcode.make(pay_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"type": "image", "data": {"file": f"base64://{b64}"}}


class LibraryBotHandler:
    def __init__(self, client: Optional[LibraryClient] = None, ai: Optional[AIService] = None):
        self.client = client or LibraryClient()
        self.ai = ai or AIService()

    async def handle(
        self, event: Dict[str, Any], bot_qq: str
    ) -> Optional[Tuple[str, Optional[List[Dict[str, Any]]]]]:
        message_type = event.get("message_type")
        if message_type not in ("group", "private"):
            return None

        user_id = event.get("user_id")
        if str(user_id) == str(event.get("self_id")):
            return None

        is_private = message_type == "private"
        scope_id = private_scope_id(user_id) if is_private else event.get("group_id")

        raw_message = event.get("message", "")
        text = strip_group_prefix(_plain_text(raw_message).strip())
        if not text:
            return None

        if not is_private:
            at_bot = has_at_bot(raw_message, bot_qq)
            if not at_bot and not is_flow_message(text):
                return None

        if text in HELP_WORDS:
            return (help_text_private() if is_private else help_text()), None

        if text in BALANCE_WORDS:
            return await self._handle_balance(user_id)

        if text in RESEND_WORDS:
            return await self._handle_resend(user_id, scope_id)

        buy_match = BUY_PATTERN.match(text)
        if buy_match:
            return await self._handle_buy(user_id, scope_id, buy_match.group(1))

        if INDEX_PATTERN.fullmatch(text):
            return await self._handle_select(user_id, scope_id, int(text))

        if is_private:
            query = text
        else:
            query = extract_at_query(raw_message, bot_qq)
            if query is None:
                return None

        if re.search(r"https?://", query, re.I):
            hint = (
                "不支持打开外部链接。请直接发送标准号或名称查询，例如：GB50016。"
                if is_private
                else f"不支持打开外部链接。请 @我 + 标准号或名称查询，例如：GB50016。"
            )
            return hint, None

        if is_direct_search_query(query):
            return await self._handle_search(user_id, scope_id, query)

        intent = local_intent_parse(query)
        from_deepseek = False
        if not intent or intent.get("intent") == "unsupported":
            intent = await self.ai.recognize_intent(query, str(user_id), str(scope_id))
            from_deepseek = bool(intent.get("_from_deepseek"))

        handled = await self._execute_intent(intent, user_id, scope_id, query)
        if handled is not None:
            text, segments, used_ai = handled
            if from_deepseek or used_ai:
                text = tag_ai_reply(text)
            return text, segments

        reply, from_ai = await self.ai.smalltalk(query, str(user_id), str(scope_id))
        if from_ai:
            reply = tag_ai_reply(reply)
        return reply, None

    async def _execute_intent(
        self,
        intent: Dict[str, Any],
        user_id: Any,
        group_id: Any,
        fallback_text: str,
    ) -> Optional[Tuple[str, Optional[List[Dict[str, Any]]], bool]]:
        scope_id = group_id
        name = intent.get("intent") or "unsupported"

        if name == "search_document":
            q = intent.get("query") or fallback_text
            text, segments = await self._handle_search(user_id, scope_id, q)
            return text, segments, False

        if name == "select_result":
            idx = intent.get("index")
            if idx:
                text, segments = await self._handle_select(user_id, scope_id, int(idx))
                return text, segments, False
            return None

        if name == "buy_ticket":
            pack_code = intent.get("pack_code")
            if pack_code:
                pack_num = pack_code.replace("ticket_", "")
                text, segments = await self._handle_buy(user_id, scope_id, pack_num)
                return text, segments, False
            return None

        if name == "check_balance":
            text, segments = await self._handle_balance(user_id)
            return text, segments, False

        if name == "resend_link":
            text, segments = await self._handle_resend(user_id, scope_id)
            return text, segments, False

        if name == "help":
            return (help_text_private() if is_private_scope(scope_id) else help_text()), None, False

        if name == "smalltalk":
            reply, from_ai = await self.ai.smalltalk(fallback_text, str(user_id), str(scope_id))
            return reply, None, from_ai

        return None

    async def _handle_search(
        self, user_id: Any, scope_id: Any, query: str
    ) -> Tuple[str, None]:
        try:
            session = await self.client.create_search_session(str(user_id), str(scope_id), query)
        except Exception as e:
            return f"搜索服务暂时不可用（{type(e).__name__}），请稍后重试。", None
        items = session.get("data") or session.get("results") or []
        if not items and session.get("message") == "not found":
            return format_search_results([]), None
        if not items:
            try:
                search = await self.client.search(query)
                items = search.get("data") or []
            except Exception as e:
                return f"搜索服务暂时不可用（{type(e).__name__}），请稍后重试。", None
        return format_search_results(items), None

    async def _handle_select(
        self, user_id: Any, scope_id: Any, index: int
    ) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        try:
            data = await self.client.select_download(str(user_id), str(scope_id), index)
        except Exception as e:
            return f"下载服务暂时不可用（{type(e).__name__}），请稍后重试。", None
        if data.get("error_code") == "NO_ACTIVE_SESSION":
            return data.get("message"), None
        if not data.get("success"):
            return data.get("message", "下载失败"), None
        if data.get("need_pay"):
            return format_need_pay(data), None
        return format_download_success(data), None

    async def _handle_buy(
        self, user_id: Any, scope_id: Any, pack_num: str
    ) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        pack_code = PACK_MAP[pack_num]
        data = await self.client.create_ticket_order(str(user_id), str(scope_id), pack_code)
        if not data.get("success"):
            return data.get("message", "创建订单失败"), None
        pay_url = data.get("pay_url")
        segments = [make_qr_image_segment(pay_url)] if pay_url else None
        return format_order_created(data), segments

    async def _handle_balance(self, user_id: Any) -> Tuple[str, None]:
        data = await self.client.wallet(str(user_id))
        return format_wallet(data), None

    async def _handle_resend(
        self, user_id: Any, scope_id: Any
    ) -> Tuple[str, None]:
        data = await self.client.resend(str(user_id), str(scope_id))
        if not data.get("success"):
            return data.get("message", "重发失败"), None
        return format_resend(data), None


def _plain_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if not isinstance(message, list):
        return ""
    parts = []
    for seg in message:
        if isinstance(seg, dict) and seg.get("type") == "text":
            parts.append(seg.get("data", {}).get("text", ""))
    return "".join(parts)
