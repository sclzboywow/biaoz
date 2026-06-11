#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from typing import Dict, List, Optional

BOT_DISPLAY_NAME = "标准库助手"

AI_REPLY_TAG = " [AI]"

FALLBACK_REPLY = "我主要负责群内资料查询。请直接 @我 + 编号或名称，例如：GB50016。"

FALLBACK_REPLY_PRIVATE = "我主要负责资料查询。私聊直接发送标准号或名称即可，例如：GB50016。"


def tag_ai_reply(text: str) -> str:
    text = (text or "").rstrip()
    if text.endswith("[AI]"):
        return text
    return f"{text}{AI_REPLY_TAG}"


def help_text_short() -> str:
    return (
        "使用方法：\n\n"
        "1. 查询资料：\n"
        f"@{BOT_DISPLAY_NAME} GB50016\n\n"
        "2. 选择资料：\n"
        "回复编号，例如：1\n\n"
        "3. 购买下载券：\n"
        "买1、买10、买25\n\n"
        "4. 查看余额：\n"
        "余额\n\n"
        "5. 重发链接：\n"
        "重发\n\n"
        "查询免费，下载消耗下载券。"
    )


def help_text_private_short() -> str:
    return (
        "使用方法：\n\n"
        "1. 查询资料：\n"
        "直接发送编号或名称，例如：GB50016\n\n"
        "2. 选择资料：\n"
        "回复编号，例如：1\n\n"
        "3. 购买下载券：\n"
        "买1、买10、买25\n\n"
        "4. 查看余额：\n"
        "余额\n\n"
        "5. 重发链接：\n"
        "重发\n\n"
        "查询免费，下载消耗下载券。"
    )


def help_text() -> str:
    return help_text_short()


def help_text_private() -> str:
    return help_text_private_short()


RATE_LIMIT_USER_REPLY = "操作有点频繁，我主要负责资料查询。请直接 @我 + 编号或名称。"

RATE_LIMIT_GROUP_REPLY = "当前群 AI 回复次数较多，已切换为简洁模式。查询资料请直接 @我 + 编号或名称。"

TOO_LONG_REPLY = "内容太长了。我主要用于资料查询，请直接发送资料编号或名称。"

FORBIDDEN_KEYWORDS = [
    "微信", "加我", "私聊", "私信", "联系客服", "人工客服",
    "qq群", "进群", "加群", "官网", "网址", "http", "https", "www",
    "扫码加", "联系管理员", "站外", "外部平台", "点击链接",
]

FAQ_REPLIES: Dict[str, str] = {
    "你是谁": "我是标准库助手，主要帮你查规范、标准、图集资料。直接 @我 + 编号或名称即可。",
    "你会什么": "我主要会查资料、找标准、发图集链接。你可以直接 @我，例如：GB50016。",
    "你会干嘛": "我主要会查资料、找标准、发图集链接。你可以直接 @我，例如：GB50016。",
    "怎么用": help_text_short(),
    "怎么买": "购买下载券请直接回复：买1、买10 或 买25。查询资料仍免费。",
    "下载券是什么": "查询资料免费，下载完整资料需要下载券。1张券可下载1份资料。",
    "余额怎么看": "请直接回复：余额",
    "链接失效怎么办": "24小时内可回复：重发。超过24小时请重新选择资料下载。",
    "为什么要付费": "查询资料免费，下载完整资料需要下载券。1张券可下载1份资料。",
    "找不到资料怎么办": "可以换标准号、简称或关键词试试，比如 GB50016、16G101、建筑防火规范。",
}


def normalize_faq_key(text: str) -> str:
    t = re.sub(r"\s+", "", (text or "").strip().lower())
    t = t.replace("？", "?").replace("?", "")
    return t


def match_faq(text: str) -> Optional[str]:
    key = normalize_faq_key(text)
    for k, v in FAQ_REPLIES.items():
        if normalize_faq_key(k) == key or key in normalize_faq_key(k) or normalize_faq_key(k) in key:
            return v
    return None


def format_search_results(items: List[dict]) -> str:
    if not items:
        return (
            "未找到相关资料。\n\n"
            "你可以换一种写法试试：\n"
            "1. 标准号：GB50016\n"
            "2. 图集号：16G101\n"
            "3. 名称：建筑设计防火规范"
        )
    lines = [f"找到以下资料（{len(items)}个）：", ""]
    for idx, item in enumerate(items, start=1):
        category = item.get("category") or "未分类"
        lines.append(f"{idx}. {item.get('code')} {item.get('title')}")
        lines.append(f"   分类：{category}｜消耗：{item.get('ticket_cost', 1)}张券")
        lines.append("")
    lines.append("回复编号下载，例如：1")
    lines.append("结果 5 分钟内有效。")
    return "\n".join(lines)


def format_download_success(data: dict) -> str:
    if data.get("message"):
        return str(data["message"])
    doc = data.get("document") or {}
    share = data.get("share") or {}
    period = share.get("period_label") or "7天"
    lines = [
        "资料下载成功",
        "",
        f"名称：{doc.get('code')} {doc.get('title')}".strip(),
        f"链接：{data.get('pan_share_url')}",
        f"提取码：{data.get('pan_extract_code') or '无'}",
        f"有效期：{period}",
        "",
    ]
    if data.get("free_download"):
        lines.extend(
            [
                "【测试模式】本次未扣除下载券。",
                f"当前余额：{data.get('balance', 0)}张",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"已扣除：{data.get('ticket_cost', 1)}张下载券",
                f"剩余：{data.get('balance', 0)}张",
                "",
            ]
        )
    lines.append("24小时内链接失效可回复：重发")
    return "\n".join(lines)


def format_need_pay(data: dict) -> str:
    cost = data.get("ticket_cost", 1)
    return (
        "你当前没有下载券。\n\n"
        f"下载该资料需要 {cost} 张下载券。\n\n"
        "购买：\n"
        "买1 = 1.99元\n"
        "买10 = 9.9元\n"
        "买25 = 19.9元"
    )


PACK_NAMES = {
    "ticket_1": "1张下载券",
    "ticket_10": "10张下载券",
    "ticket_25": "25张下载券",
}


def format_order_created(data: dict) -> str:
    amount = data.get("amount_cent", 0) / 100
    pack_name = data.get("pack_name") or PACK_NAMES.get(data.get("pack_code"), "")
    return (
        "订单已生成：\n\n"
        f"套餐：{pack_name}\n"
        f"金额：{amount:g}元\n"
        f"到账：{data.get('ticket_count')}张下载券\n\n"
        "请扫码支付：\n"
        "（二维码见下一条消息）\n\n"
        "二维码有效期：10分钟。\n"
        "支付成功后自动到账。"
    )


def format_wallet(data: dict) -> str:
    lines = [f"你的下载券余额：{data.get('balance', 0)} 张", ""]
    recent = data.get("recent_downloads") or []
    if recent:
        lines.append("最近下载：")
        for idx, item in enumerate(recent, start=1):
            lines.append(f"{idx}. {item.get('code')} {item.get('title')}")
        lines.append("")
    lines.append("查询资料请直接发送编号或名称，例如：GB50016。")
    return "\n".join(lines)


def format_resend(data: dict) -> str:
    if data.get("message"):
        return "已为你重发最近一次下载链接：\n\n" + str(data["message"])
    doc = data.get("document") or {}
    share = data.get("share") or {}
    period = share.get("period_label") or "7天"
    return (
        "已为你重发最近一次下载链接：\n\n"
        f"名称：{doc.get('code')} {doc.get('title')}\n"
        f"链接：{data.get('pan_share_url')}\n"
        f"提取码：{data.get('pan_extract_code') or '无'}\n"
        f"有效期：{period}"
    )


def format_ticket_paid_notice(data: dict) -> str:
    return (
        f"支付成功，{data.get('ticket_count', 0)}张下载券已到账。\n\n"
        f"当前余额：{data.get('balance', 0)}张。\n"
        "可以继续回复编号下载资料。"
    )


def truncate_chinese(text: str, max_len: int = 80) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def violates_policy(text: str) -> bool:
    lower = (text or "").lower()
    for kw in FORBIDDEN_KEYWORDS:
        if kw.lower() in lower:
            return True
    if re.search(r"1[3-9]\d{9}", text or ""):
        return True
    return False
