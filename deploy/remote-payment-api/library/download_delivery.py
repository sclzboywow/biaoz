#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download success payload: Chinese filename + formatted share message."""

from __future__ import annotations

import os
import re
from typing import Any


def default_share_period_days() -> int:
    raw = os.getenv("BAIDU_SHARE_PERIOD_DAYS", "7").strip()
    try:
        days = int(raw)
    except ValueError:
        days = 7
    return max(1, min(days, 365))


def period_label(days: int | None) -> str:
    value = int(days or default_share_period_days())
    return f"{value}天"


def build_chinese_filename(code: str | None, title: str | None, *, ext: str = ".pdf") -> str:
    code = (code or "").strip()
    title = (title or "").strip()
    if code and title and title != code:
        base = f"{code} {title}"
    else:
        base = code or title or "资料"
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .")
    ext = ext if ext.startswith(".") else f".{ext}"
    if not base.lower().endswith(ext.lower()):
        base += ext
    if len(base) > 120:
        stem = base[: 120 - len(ext)].rstrip(" .")
        base = stem + ext
    return base or f"资料{ext}"


def format_download_message(
    *,
    code: str,
    title: str,
    pan_share_url: str,
    pan_extract_code: str,
    period_days: int | None = None,
    ticket_cost: int = 0,
    balance: int = 0,
    free_download: bool = False,
) -> str:
    days = int(period_days or default_share_period_days())
    name = f"{code} {title}".strip()
    lines = [
        "资料下载成功",
        "",
        f"名称：{name}",
        f"链接：{pan_share_url}",
        f"提取码：{pan_extract_code or '无'}",
        f"有效期：{period_label(days)}",
        "",
    ]
    if free_download:
        lines.extend(
            [
                "【测试模式】本次未扣除下载券。",
                f"当前余额：{balance}张",
            ]
        )
    else:
        lines.extend(
            [
                f"已扣除：{ticket_cost}张下载券",
                f"剩余：{balance}张",
            ]
        )
    lines.extend(["", "24小时内可回复「重发」重发链接"])
    return "\n".join(lines)


def build_download_delivery(
    *,
    document: dict[str, Any],
    pan_share_url: str,
    pan_extract_code: str,
    period_days: int | None = None,
    ticket_cost: int = 0,
    balance: int = 0,
    free_download: bool = False,
    share_id: str | None = None,
    pan_short_url: str | None = None,
) -> dict[str, Any]:
    code = str(document.get("code") or "")
    title = str(document.get("title") or "")
    days = int(period_days or default_share_period_days())
    display_name = build_chinese_filename(code, title)
    message = format_download_message(
        code=code,
        title=title,
        pan_share_url=pan_share_url,
        pan_extract_code=pan_extract_code,
        period_days=days,
        ticket_cost=ticket_cost,
        balance=balance,
        free_download=free_download,
    )
    return {
        "share": {
            "pan_share_url": pan_share_url,
            "pan_extract_code": pan_extract_code,
            "period_days": days,
            "period_label": period_label(days),
            "share_id": share_id or "",
            "pan_short_url": pan_short_url or "",
        },
        "file": {
            "display_name": display_name,
        },
        "message": message,
    }


def enrich_download_result(result: dict[str, Any], share_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    if not result.get("success") or result.get("need_pay"):
        return result
    doc = result.get("document") or {}
    meta = share_meta or {}
    delivery = build_download_delivery(
        document=doc,
        pan_share_url=str(result.get("pan_share_url") or ""),
        pan_extract_code=str(result.get("pan_extract_code") or ""),
        period_days=meta.get("period_days") or result.get("share_period_days"),
        ticket_cost=int(result.get("ticket_cost") or 0),
        balance=int(result.get("balance") or 0),
        free_download=bool(result.get("free_download")),
        share_id=str(meta.get("share_id") or ""),
        pan_short_url=str(meta.get("pan_short_url") or ""),
    )
    result.update(delivery)
    return result
