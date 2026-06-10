"""Probe TTBZ portal API + PDF fileUrl flow (optionally via SOCKS proxy)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

import httpx

from app.http_proxy import resolve_ttbz_http_proxy

TTBZ_API = "https://www.ttbz.org.cn/cms-proxy/ms/portal/standardInfo"
TTBZ_ORIGIN = "https://www.ttbz.org.cn"


def build_client(*, proxy: str | None, timeout: int) -> httpx.Client:
    kwargs: dict = {
        "follow_redirects": True,
        "timeout": timeout,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": f"{TTBZ_ORIGIN}/standard.html",
        },
    }
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http-proxy", default="")
    parser.add_argument("--unique-id", default="")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    proxy = (args.http_proxy or "").strip() or resolve_ttbz_http_proxy()
    with build_client(proxy=proxy, timeout=args.timeout) as client:
        if args.unique_id:
            uid = args.unique_id.strip()
        else:
            resp = client.post(
                f"{TTBZ_API}/getPortalStandardList",
                data={"pageNo": 1, "pageSize": 5, "isOpen": "1"},
            )
            print("list_status", resp.status_code)
            resp.raise_for_status()
            rows = (resp.json().get("data") or {}).get("rows") or []
            uid = rows[0]["standardUniqueId"] if rows else ""
            print("sample_row", json.dumps(rows[0] if rows else {}, ensure_ascii=False)[:500])

        for endpoint in ("getPortalStandardById", "getStandardDetail"):
            resp = client.post(f"{TTBZ_API}/{endpoint}", data={"standardUniqueId": uid})
            print(f"{endpoint}_status", resp.status_code, (resp.headers.get("content-type") or "")[:40])
            if resp.status_code != 200:
                print(f"{endpoint}_body", resp.text[:200])
                continue
            detail = (resp.json().get("data") or {}) if resp.text else {}
            files = detail.get("files") or []
            print(
                f"{endpoint}_meta",
                json.dumps(
                    {
                        "standardNo": detail.get("standardNo"),
                        "hasCnPdf": detail.get("hasCnPdf"),
                        "isOpenName": detail.get("isOpenName"),
                        "files_count": len(files),
                        "file0": files[0] if files else None,
                    },
                    ensure_ascii=False,
                ),
            )

        portal = client.post(f"{TTBZ_API}/getPortalStandardById", data={"standardUniqueId": uid})
        portal.raise_for_status()
        detail = portal.json().get("data") or {}
        files = detail.get("files") or []
        file_url = ""
        if detail.get("hasCnPdf") and files:
            file_url = str((files[0] or {}).get("fileUrl") or "").strip()
        if not file_url:
            print("no_file_url", json.dumps({"hasCnPdf": detail.get("hasCnPdf"), "files": files}, ensure_ascii=False))
            return 0

        pdf_url = file_url if file_url.startswith("http") else f"{TTBZ_ORIGIN}{file_url}"
        pdf_resp = client.get(
            pdf_url,
            headers={
                "User-Agent": client.headers.get("User-Agent", ""),
                "Referer": f"{TTBZ_ORIGIN}/standardDetail/{uid}.html",
                "Accept": "application/pdf,*/*",
            },
        )
        print(
            "pdf_get",
            json.dumps(
                {
                    "url": str(pdf_resp.url),
                    "status": pdf_resp.status_code,
                    "content_type": pdf_resp.headers.get("content-type"),
                    "size": len(pdf_resp.content),
                    "is_pdf": pdf_resp.content[:4] == b"%PDF",
                    "head": pdf_resp.content[:16].hex() if pdf_resp.content else "",
                    "text_head": (pdf_resp.text or "")[:120],
                },
                ensure_ascii=False,
            ),
        )

        dl = client.post(
            f"{TTBZ_API}/downLoadStandard",
            data={"standardUniqueId": uid},
            headers={"Accept": "application/pdf,*/*", "Referer": f"{TTBZ_ORIGIN}/standardDetail/{uid}.html"},
        )
        print(
            "downLoadStandard",
            json.dumps(
                {
                    "status": dl.status_code,
                    "content_type": dl.headers.get("content-type"),
                    "size": len(dl.content),
                    "is_pdf": dl.content[:4] == b"%PDF",
                    "text_head": (dl.text or "")[:120],
                },
                ensure_ascii=False,
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
