from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx

from app.http_proxy import resolve_ttbz_http_proxy

proxy = resolve_ttbz_http_proxy()
try:
    response = httpx.get(
        "https://www.ttbz.org.cn/standard.html",
        proxy=proxy,
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.ttbz.org.cn/"},
    )
    print(f"site_via_proxy {response.status_code} {len(response.text)}")
except Exception as exc:
    print(f"site_via_proxy_error {exc!r}")
