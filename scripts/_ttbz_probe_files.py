"""Probe TTBZ file types and download endpoints."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

import httpx

from app.http_proxy import resolve_ttbz_http_proxy

API = "https://www.ttbz.org.cn/cms-proxy/ms/portal/standardInfo"
ORIGIN = "https://www.ttbz.org.cn"


def client() -> httpx.Client:
    proxy = resolve_ttbz_http_proxy()
    kwargs = {
        "timeout": 30,
        "follow_redirects": True,
        "headers": {"User-Agent": "Mozilla/5.0", "Referer": f"{ORIGIN}/standard.html"},
    }
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


def main() -> int:
    with client() as c:
        type_stats: dict[str, int] = {}
        with_pdf_url = 0
        multi_types = 0
        samples: list[dict] = []
        for page in range(1, 11):
            rows = c.post(f"{API}/getPortalStandardList", data={"pageNo": page, "pageSize": 50, "isOpen": "1"}).json()[
                "data"
            ]["rows"]
            for row in rows:
                uid = row["standardUniqueId"]
                detail = c.post(f"{API}/getPortalStandardById", data={"standardUniqueId": uid}).json().get("data") or {}
                files = detail.get("files") or []
                for f in files:
                    key = f"{f.get('fileType')}:{f.get('fileTypeName')}"
                    type_stats[key] = type_stats.get(key, 0) + 1
                if detail.get("standardPdfUrl"):
                    with_pdf_url += 1
                    if len(samples) < 5:
                        samples.append(
                            {
                                "standardNo": row.get("standardNo"),
                                "standardPdfUrl": detail.get("standardPdfUrl"),
                                "files": files,
                            }
                        )
                types = {(f.get("fileType"), f.get("fileTypeName")) for f in files}
                if len(types) > 1 and len(samples) < 8:
                    multi_types += 1
                    samples.append({"standardNo": row.get("standardNo"), "files": files})
            time.sleep(0.2)
        print("type_stats", json.dumps(type_stats, ensure_ascii=False))
        print("with_standardPdfUrl", with_pdf_url, "multi_type_samples", multi_types)
        print("samples", json.dumps(samples[:8], ensure_ascii=False))

        uid = "72q47wskiu7m7i0rzxjtrnm3iceyvge"
        ref = f"{ORIGIN}/standardDetail/{uid}.html"
        for ep in ("downLoadStandard", "downloadStandard"):
            r = c.post(
                f"{API}/{ep}",
                data={"standardUniqueId": uid},
                headers={"Accept": "application/pdf,*/*", "Referer": ref},
            )
            print(
                ep,
                json.dumps(
                    {
                        "status": r.status_code,
                        "ctype": r.headers.get("content-type"),
                        "size": len(r.content),
                        "is_pdf": r.content[:4] == b"%PDF",
                        "head": (r.text or "")[:120],
                    },
                    ensure_ascii=False,
                ),
            )
        html = c.get(ref).text
        urls = sorted(set(re.findall(r"/UploadFiles/[^\s\"']+\.pdf", html)))
        print("html_pdf_urls", urls[:10])
        print("standardPdfUrl_in_html", "standardPdfUrl" in html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
