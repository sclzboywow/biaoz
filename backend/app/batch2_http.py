"""Shared HTTP helpers for batch-2 adapters (no adapter imports)."""

from __future__ import annotations

import os
import time
from urllib.parse import urljoin

import httpx

BATCH2_RETRY_ATTEMPTS = int(os.getenv("BATCH2_RETRY_ATTEMPTS", "3"))


def default_headers(referer: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 StandardDocsBatch2/1.0",
        "Accept": "application/json,text/html,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def make_client(referer: str | None = None, timeout: float = 30) -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers=default_headers(referer),
    )


def absolute_url(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith("http"):
        return href
    return urljoin(base_url.rstrip("/") + "/", href.lstrip("/"))


def fetch_html(client: httpx.Client, url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, BATCH2_RETRY_ATTEMPTS + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < BATCH2_RETRY_ATTEMPTS:
                time.sleep(min(2 * attempt, 8))
    raise RuntimeError(f"fetch failed for {url}: {last_error}")
