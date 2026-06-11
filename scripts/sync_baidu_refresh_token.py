#!/usr/bin/env python3
"""Read baidu refresh_token from local PG and sync to server account file."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")


def parse_account_file(path: Path) -> dict[str, str]:
    key_map = {
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


def upsert_account_lines(path: Path, updates: dict[str, str]) -> None:
    labels = {
        "refresh_token": "refresh_token",
        "access_token": "access_token",
    }
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    lines = text.splitlines()
    for key, value in updates.items():
        if not value:
            continue
        label = labels.get(key, key)
        pattern = re.compile(rf"^{re.escape(label)}\s*[:=：]", re.I)
        replaced = False
        for i, line in enumerate(lines):
            if pattern.match(line.strip()):
                lines[i] = f"{label}:{value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{label}:{value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def load_refresh_from_db() -> str:
    from sqlalchemy import text
    from app.database import SessionLocal

    with SessionLocal() as db:
        row = db.execute(
            text("SELECT value FROM system_settings WHERE key = 'baidu_pan_refresh_token' LIMIT 1")
        ).first()
        if row and row[0]:
            return str(row[0]).strip()
    return ""


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode()
    req = urllib.request.Request(
        "https://openapi.baidu.com/oauth/2.0/token?grant_type=refresh_token&openapi=xpansdk",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(json.dumps({k: v for k, v in payload.items() if k != "access_token"}, ensure_ascii=False))
    return str(token)


def quota(access_token: str) -> dict:
    url = (
        "https://pan.baidu.com/api/quota?"
        + urllib.parse.urlencode({"access_token": access_token, "method": "quota"})
    )
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    account_path = Path(os.getenv("BAIDU_PAN_ACCOUNT_FILE") or ROOT / "openxpanapi" / "账户信息.txt")
    if not account_path.is_absolute():
        account_path = (ROOT / account_path).resolve()

    refresh = os.getenv("BAIDU_PAN_REFRESH_TOKEN", "").strip()
    if not refresh:
        try:
            refresh = load_refresh_from_db()
        except Exception as exc:
            print(json.dumps({"status": "error", "step": "load_db", "message": str(exc)}))
            return 1

    if not refresh:
        print(json.dumps({"status": "error", "message": "refresh_token not found in env or database"}))
        return 1

    account = parse_account_file(account_path)
    client_id = os.getenv("BAIDU_PAN_CLIENT_ID") or account.get("client_id") or ""
    client_secret = os.getenv("BAIDU_PAN_CLIENT_SECRET") or account.get("client_secret") or ""
    if not client_id or not client_secret:
        print(json.dumps({"status": "error", "message": "missing client_id/client_secret in account file"}))
        return 1

    upsert_account_lines(account_path, {"refresh_token": refresh})
    token = refresh_access_token(client_id, client_secret, refresh)
    upsert_account_lines(account_path, {"access_token": token})
    q = quota(token)
    free = int(q.get("free") or 0)
    used = int(q.get("used") or 0)
    print(
        json.dumps(
            {
                "status": "success",
                "account_file": str(account_path),
                "has_refresh_token": True,
                "access_token_len": len(token),
                "quota_free_gb": round(free / 1024 / 1024 / 1024, 2),
                "quota_used_gb": round(used / 1024 / 1024 / 1024, 2),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
