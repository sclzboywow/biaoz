#!/usr/bin/env python3
"""Baidu Pan OAuth + share helpers for payment-api (reads openxpanapi account file)."""
from __future__ import annotations

import json
import os
import re
import secrets
import string
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_cached_access_token: str | None = None


class BaiduPanError(RuntimeError):
    pass


def _account_file() -> Path:
    raw = (os.getenv("BAIDU_PAN_ACCOUNT_FILE") or "/home/ubuntu/openxpanapi/账户信息.txt").strip()
    path = Path(raw).expanduser()
    return path


def parse_account_file(path: Path | None = None) -> dict[str, str]:
    path = path or _account_file()
    key_map = {
        "appid": "appid",
        "appkey": "client_id",
        "secretkey": "client_secret",
        "access_token": "access_token",
        "refresh_token": "refresh_token",
    }
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        match = re.match(r"^([^:=：\s]+)\s*[:=：]\s*(.+)$", line)
        if not match:
            continue
        key = re.sub(r"[^0-9A-Za-z_]+", "", match.group(1)).lower()
        mapped = key_map.get(key)
        if mapped:
            result[mapped] = match.group(2).strip().strip('"').strip("'")
    return result


def _http_json(url: str, *, data: bytes | None = None, method: str = "GET", timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, data=data, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def get_access_token(*, force_refresh: bool = False) -> str:
    global _cached_access_token
    env_token = os.getenv("BAIDU_NETDISK_ACCESS_TOKEN", "").strip() or os.getenv("BAIDU_PAN_ACCESS_TOKEN", "").strip()
    if env_token and not force_refresh:
        return env_token

    with _lock:
        if _cached_access_token and not force_refresh:
            return _cached_access_token

        account = parse_account_file()
        if account.get("access_token") and not force_refresh:
            _cached_access_token = account["access_token"]
            return _cached_access_token

        refresh_token = account.get("refresh_token") or os.getenv("BAIDU_PAN_REFRESH_TOKEN", "").strip()
        client_id = account.get("client_id") or os.getenv("BAIDU_PAN_CLIENT_ID", "").strip()
        client_secret = account.get("client_secret") or os.getenv("BAIDU_PAN_CLIENT_SECRET", "").strip()
        if not (refresh_token and client_id and client_secret):
            raise BaiduPanError("missing refresh_token or app credentials")

        body = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ).encode()
        url = "https://openapi.baidu.com/oauth/2.0/token?grant_type=refresh_token&openapi=xpansdk"
        payload = _http_json(url, data=body, method="POST")
        token = str(payload.get("access_token") or "")
        if not token:
            raise BaiduPanError(f"refresh failed: {json.dumps(payload, ensure_ascii=False)[:300]}")
        _cached_access_token = token
        return token


def quota() -> dict[str, Any]:
    token = get_access_token()
    url = "https://pan.baidu.com/api/quota?" + urllib.parse.urlencode({"access_token": token, "method": "quota"})
    return _http_json(url)


def _share_password() -> str:
    alphabet = string.digits + string.ascii_lowercase
    return "".join(secrets.choice(alphabet) for _ in range(4))


def create_share_link(fs_id: str, *, period_days: int = 7, remark: str = "") -> dict[str, str] | None:
    """Create share link via apaas API (see pan.baidu.com/union/doc/Tlaaocmkj)."""
    fs_id = (fs_id or "").strip()
    if not fs_id:
        return None

    account = parse_account_file()
    appid = (
        os.getenv("BAIDU_PAN_APP_ID")
        or account.get("appid")
        or account.get("client_id")
        or ""
    ).strip()
    if not appid:
        raise BaiduPanError("missing appid for share API")

    token = get_access_token()
    url = "https://pan.baidu.com/apaas/1.0/share/set?" + urllib.parse.urlencode(
        {
            "product": "netdisk",
            "appid": appid,
            "access_token": token,
        }
    )
    body = urllib.parse.urlencode(
        {
            "fsid_list": json.dumps([fs_id], separators=(",", ":")),
            "period": str(period_days),
            "pwd": _share_password(),
            "remark": remark or "standard-doc",
        }
    ).encode()
    payload = _http_json(url, data=body, method="POST")
    if payload.get("errno") not in (0, None):
        return None
    data = payload.get("data") or {}
    link = str(data.get("link") or payload.get("link") or "")
    if not link:
        return None
    pwd = str(data.get("pwd") or payload.get("pwd") or "")
    short_url = str(data.get("short_url") or "")
    period_days = int(data.get("period") or period_days)
    return {
        "pan_share_url": link,
        "pan_extract_code": pwd,
        "pan_short_url": short_url,
        "share_id": str(data.get("share_id") or ""),
        "period_days": period_days,
    }


def health() -> dict[str, Any]:
    account = parse_account_file()
    result = {
        "account_file": str(_account_file()),
        "has_refresh_token": bool(account.get("refresh_token") or os.getenv("BAIDU_PAN_REFRESH_TOKEN")),
        "has_client_id": bool(account.get("client_id")),
        "has_client_secret": bool(account.get("client_secret")),
    }
    try:
        token = get_access_token()
        q = quota()
        result.update(
            {
                "ok": True,
                "access_token_len": len(token),
                "quota_total_gb": round(int(q.get("total") or 0) / 1024**3, 2),
                "quota_used_gb": round(int(q.get("used") or 0) / 1024**3, 2),
                "quota_free_gb": round(int(q.get("free") or 0) / 1024**3, 2),
            }
        )
    except Exception as exc:
        result.update({"ok": False, "error": str(exc)})
    return result
