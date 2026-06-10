"""Extract RSA public key used by TTBZ pdf-preview."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

import websockets

from app.ttbz_browser_session import fetch_ttbz_browser_cookies, resolve_ttbz_cdp_url

ORIGIN = "https://www.ttbz.org.cn"


async def run(uid: str, cookies: list[dict]) -> dict:
    cdp = resolve_ttbz_cdp_url()
    pages = json.loads(urllib.request.urlopen(f"{cdp.rstrip('/')}/json/list", timeout=10).read())
    ws_url = pages[0]["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, max_size=8_000_000) as ws:
        mid = 1

        async def call(method: str, params: dict | None = None) -> dict:
            nonlocal mid
            i = mid
            mid += 1
            await ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
            while True:
                data = json.loads(await ws.recv())
                if data.get("id") == i:
                    if "error" in data:
                        raise RuntimeError(data["error"])
                    return data.get("result") or {}

        await call("Runtime.enable")
        await call("Page.enable")
        for item in cookies:
            await call(
                "Network.setCookie",
                {
                    "name": item.get("name"),
                    "value": item.get("value"),
                    "domain": str(item.get("domain") or "www.ttbz.org.cn").lstrip("."),
                    "path": str(item.get("path") or "/"),
                },
            )
        detail = f"{ORIGIN}/standardDetail/{uid}.html"
        await call("Page.navigate", {"url": detail})
        await asyncio.sleep(6)
        go_js = f"""
        (() => {{
          window.UrlUtils.setPdfPreviewCookie({json.dumps(uid)}, 'cn', 1);
          window.location.href = '/ms/pdf-preview';
        }})()
        """
        await call("Runtime.evaluate", {"expression": go_js})
        await asyncio.sleep(12)
        extract_js = """
        (() => {
          const out = { globals: [] };
          for (const key of Object.keys(window)) {
            if (/key|rsa|encrypt|JSEncrypt/i.test(key)) out.globals.push(key);
          }
          if (window.JSEncrypt) out.hasJSEncrypt = true;
          return out;
        })()
        """
        info = await call("Runtime.evaluate", {"expression": extract_js, "returnByValue": True})
        return (info.get("result") or {}).get("value") or {}


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    cdp = resolve_ttbz_cdp_url()
    cookies = fetch_ttbz_browser_cookies(cdp_url=cdp) if cdp else []
    print(json.dumps(asyncio.run(run(uid, cookies)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
