"""Try getStdPdfWatermarked operateType=2 for clean PDF URL."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

import httpx

from app.http_proxy import resolve_ttbz_http_proxy
from app.ttbz_browser_session import apply_ttbz_browser_cookies, resolve_ttbz_cdp_url

ORIGIN = "https://www.ttbz.org.cn"


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    ref = f"{ORIGIN}/standardDetail/{uid}.html"
    client = httpx.Client(
        timeout=60,
        follow_redirects=True,
        proxy=resolve_ttbz_http_proxy(),
        headers={"User-Agent": "Mozilla/5.0", "Referer": ref, "X-Requested-With": "XMLHttpRequest"},
    )
    apply_ttbz_browser_cookies(client, cdp_url=resolve_ttbz_cdp_url())
    html = client.get(ref).text
    match = re.search(r'API_PREFIX\s*=\s*["\']([^"\']+)["\']', html)
    api_prefix = match.group(1) if match else "/cms-proxy"
    print("api_prefix", api_prefix)

    for op in (1, 2):
        response = client.post(
            f"{ORIGIN}{api_prefix}/ms/bus/standardInfo/getStdPdfWatermarked",
            data={"operateType": str(op), "standardUniqueId": uid, "fileLang": "cn"},
            headers={
                "Referer": ref,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json,*/*",
            },
        )
        print("op", op, "status", response.status_code, "ctype", response.headers.get("content-type"))
        if response.headers.get("content-type", "").startswith("application/json"):
            payload = response.json()
            print("json", json.dumps(payload, ensure_ascii=False)[:500])
            data = payload.get("data")
            if isinstance(data, str) and data.strip():
                pdf_url = data if data.startswith("http") else f"{ORIGIN}{data}"
                pdf_resp = client.get(pdf_url, headers={"Referer": ref, "Accept": "application/pdf,*/*"})
                print(
                    "pdf",
                    json.dumps(
                        {
                            "url": pdf_url[:200],
                            "status": pdf_resp.status_code,
                            "size": len(pdf_resp.content),
                            "is_pdf": pdf_resp.content.startswith(b"%PDF"),
                        },
                        ensure_ascii=False,
                    ),
                )
        else:
            print("head", (response.text or "")[:150])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
