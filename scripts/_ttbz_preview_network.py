"""Simple CDP probe: open pdf-preview tab and list network URLs."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

import websockets

from app.ttbz_browser_session import fetch_ttbz_browser_cookies, resolve_ttbz_cdp_url

ORIGIN = "https://www.ttbz.org.cn"


def cookie_value(uid: str) -> str:
    payload = json.dumps({"mode": "api", "standardUniqueId": uid, "lang": "cn", "type": 1}, separators=(",", ":"))
    return base64.b64encode(urllib.parse.quote(payload, safe="").encode()).decode()


async def main(uid: str, cookies: list[dict]) -> None:
    cdp = resolve_ttbz_cdp_url()
    pages = json.loads(urllib.request.urlopen(f"{cdp.rstrip('/')}/json/list", timeout=10).read())
    target = pages[0]
    urls: list[str] = []

    async with websockets.connect(target["webSocketDebuggerUrl"], max_size=8_000_000) as ws:
        mid = 1

        async def send(method: str, params: dict | None = None) -> int:
            nonlocal mid
            i = mid
            mid += 1
            await ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
            return i

        async def recv_until(id_: int) -> dict:
            while True:
                data = json.loads(await ws.recv())
                if data.get("method") == "Network.responseReceived":
                    url = ((data.get("params") or {}).get("response") or {}).get("url") or ""
                    if url:
                        urls.append(url)
                if data.get("id") == id_:
                    if "error" in data:
                        raise RuntimeError(data["error"])
                    return data.get("result") or {}

        await send("Network.enable")
        await send("Page.enable")
        for item in cookies:
            await send(
                "Network.setCookie",
                {
                    "name": item.get("name"),
                    "value": item.get("value"),
                    "domain": str(item.get("domain") or "www.ttbz.org.cn").lstrip("."),
                    "path": str(item.get("path") or "/"),
                },
            )
        await send(
            "Network.setCookie",
            {"name": "_pdf_preview", "value": cookie_value(uid), "domain": "www.ttbz.org.cn", "path": "/"},
        )
        nav_id = await send("Page.navigate", {"url": f"{ORIGIN}/ms/pdf-preview"})
        await recv_until(nav_id)
        await asyncio.sleep(10)

    interesting = [u for u in urls if any(k in u.lower() for k in ("pdf", "watermark", "standard", "upload", "cipher", "public", "bus"))]
    print(json.dumps({"count": len(urls), "interesting": interesting}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    cdp = resolve_ttbz_cdp_url()
    cookies = fetch_ttbz_browser_cookies(cdp_url=cdp) if cdp else []

    async def run() -> None:
        await main(uid, cookies)

    asyncio.run(run())
