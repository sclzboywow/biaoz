#!/usr/bin/env python3
"""Server E2E: library search -> download share -> send link + file to QQ group."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PAYMENT_API = os.getenv("LIBRARY_API_BASE", "http://127.0.0.1:8000").rstrip("/")
BOT_API = os.getenv("BOT_API_BASE", "http://127.0.0.1:8765").rstrip("/")
SECRET = os.getenv("BOT_INTERNAL_SECRET", "qq-payment-internal-2026")
GROUP_ID = os.getenv("E2E_GROUP_ID", "808238349")
QQ_USER = os.getenv("E2E_QQ_USER", "215836668")
QUERY = os.getenv("E2E_QUERY", "GB50016")
INDEX = int(os.getenv("E2E_INDEX", "1"))
SKIP_FILE = os.getenv("E2E_SKIP_FILE", "").lower() in {"1", "true", "yes", "on"}

ROOT = Path("/home/ubuntu/payment-api")
sys.path.insert(0, str(ROOT))


def http_json(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    data = None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    if payload is not None:
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode()
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return exc.code, parsed


def step_search() -> dict:
    code, body = http_json(
        f"{PAYMENT_API}/api/search-sessions",
        method="POST",
        payload={
            "qq_user_id": QQ_USER,
            "group_id": GROUP_ID,
            "query_text": QUERY,
        },
    )
    items = body.get("results") or body.get("data") or []
    return {"code": code, "count": len(items), "items": items[:3], "raw": body}


def step_select() -> dict:
    code, data = http_json(
        f"{PAYMENT_API}/api/download/select",
        method="POST",
        payload={"qq_user_id": QQ_USER, "group_id": GROUP_ID, "index": INDEX},
    )
    return {"code": code, "data": data}


def format_share_text(data: dict) -> str:
    doc = data.get("document") or {}
    lines = [
        "[E2E测试] 资料下载成功",
        f"资料：{doc.get('code')} {doc.get('title')}",
        "",
        f"百度网盘：\n{data.get('pan_share_url')}",
        "",
        f"提取码：{data.get('pan_extract_code') or '无'}",
    ]
    return "\n".join(lines)


def send_group_text(text: str) -> dict:
    code, data = http_json(
        f"{BOT_API}/internal/send-group-msg",
        method="POST",
        payload={"group_id": int(GROUP_ID), "text": text},
        headers={"X-Internal-Secret": SECRET},
    )
    if code == 404:
        # fallback: NapCat HTTP action path
        webui = Path("/home/ubuntu/napcat/config/webui.json")
        token = os.getenv("NAPCAT_HTTP_TOKEN") or json.loads(webui.read_text(encoding="utf-8")).get("token", "")
        base = os.getenv("NAPCAT_HTTP_URL", "http://127.0.0.1:3001").rstrip("/")
        payload = {"group_id": int(GROUP_ID), "message": text}
        url = f"{base}/send_group_msg"
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {"status": resp.status, "body": json.loads(resp.read().decode()), "via": "napcat_http"}
    return {"code": code, "body": data, "via": "bot_internal"}


def download_sample_file(document_id: int) -> Path | None:
    from library.metadata_search import lookup_metadata_document
    from library.baidu_client import get_access_token
    from library.baidu_remark import resolve_baidu_fs_id

    doc = lookup_metadata_document(document_id)
    if not doc:
        return None
    fs_id = resolve_baidu_fs_id(file_path=doc.get("file_path"), remark=doc.get("remark"))
    if not fs_id:
        return None

    token = get_access_token()
    meta_url = "https://pan.baidu.com/rest/2.0/xpan/multimedia?" + urllib.parse.urlencode(
        {"method": "filemetas", "access_token": token, "openapi": "xpansdk"}
    )
    meta_body = urllib.parse.urlencode(
        {"fsids": json.dumps([int(fs_id)]), "dlink": "1"}
    ).encode()
    req = urllib.request.Request(meta_url, data=meta_body, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        meta = json.loads(resp.read().decode())
    items = meta.get("list") or []
    if not items:
        return None
    item = items[0]
    dlink = item.get("dlink")
    filename = str(item.get("filename") or doc.get("code") or "standard.pdf")
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    if not dlink:
        return None
    sep = "&" if "?" in dlink else "?"
    dl_url = f"{dlink}{sep}access_token={urllib.parse.quote(token, safe='')}"
    dl_req = urllib.request.Request(dl_url, headers={"User-Agent": "pan.baidu.com"})
    with urllib.request.urlopen(dl_req, timeout=120) as resp:
        content = resp.read()
    out_dir = Path("/home/ubuntu/qq-ai-bot/downloads/e2e")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename.replace("/", "_")
    out_path.write_bytes(content)
    return out_path


def send_group_file(file_path: Path, intro: str) -> dict:
    code, data = http_json(
        f"{BOT_API}/internal/qq-file/send-group",
        method="POST",
        payload={
            "group_id": int(GROUP_ID),
            "file_path": str(file_path),
            "intro_text": intro,
            "mode": "chat",
            "file_name": file_path.name,
        },
        headers={"X-Internal-Secret": SECRET},
    )
    return {"code": code, "data": data}


def main() -> int:
    report: dict = {"query": QUERY, "group_id": GROUP_ID, "qq_user": QQ_USER, "steps": {}}

    search = step_search()
    report["steps"]["search"] = search
    if search["code"] != 200 or not search["count"]:
        print(json.dumps({"status": "failed", **report}, ensure_ascii=False, indent=2))
        return 1

    select = step_select()
    report["steps"]["select"] = select
    data = select.get("data") or {}
    if select["code"] != 200 or not data.get("success") or data.get("need_pay"):
        print(json.dumps({"status": "failed", **report}, ensure_ascii=False, indent=2))
        return 1

    share_text = format_share_text(data)
    try:
        report["steps"]["group_text"] = send_group_text(share_text)
    except Exception as exc:
        report["steps"]["group_text"] = {"error": str(exc)}

    document_id = int((data.get("document") or {}).get("id") or 0)

    if not SKIP_FILE:
        file_path = None
        try:
            file_path = download_sample_file(document_id)
            report["steps"]["download"] = {
                "ok": bool(file_path),
                "path": str(file_path) if file_path else None,
                "size": file_path.stat().st_size if file_path else 0,
            }
        except Exception as exc:
            report["steps"]["download"] = {"ok": False, "error": str(exc)}

        if file_path and file_path.exists():
            intro = format_share_text(data) + "\n\n[E2E测试] 附件为网盘原文件直发。"
            try:
                report["steps"]["group_file"] = send_group_file(file_path, intro)
            except Exception as exc:
                report["steps"]["group_file"] = {"error": str(exc)}
    else:
        report["steps"]["download"] = {"skipped": True}
        report["steps"]["group_file"] = {"skipped": True}

    group_text = report["steps"].get("group_text") or {}
    body = group_text.get("body") or {}
    text_ok = group_text.get("code") == 200 or (
        group_text.get("status") == 200 and str(body.get("status", "ok")).lower() != "failed"
    )
    file_ok = bool((report["steps"].get("group_file") or {}).get("code") == 200)
    ok = bool(data.get("pan_share_url")) and text_ok
    report["status"] = "success" if ok else "partial"
    if file_ok:
        report["status"] = "success"
    report["pan_share_url"] = data.get("pan_share_url")
    report["pan_extract_code"] = data.get("pan_extract_code")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
