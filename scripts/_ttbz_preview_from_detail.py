"""Open pdf-preview via detail page cookie flow (same as 阅览中文版)."""

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
    events: list[dict] = []

    async with websockets.connect(ws_url, max_size=8_000_000) as ws:
        msg_id = 1

        async def call(method: str, params: dict | None = None) -> dict:
            nonlocal msg_id
            current = msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": current, "method": method, "params": params or {}}))
            while True:
                raw = await ws.recv()
                data = json.loads(raw)
                if "method" in data:
                    m = data["method"]
                    p = data.get("params") or {}
                    if m == "Network.requestWillBeSent":
                        req = p.get("request") or {}
                        url = req.get("url") or ""
                        if any(k in url.lower() for k in ("pdf", "watermark", "standard", "upload", "bus", "cipher")):
                            events.append(
                                {
                                    "kind": "req",
                                    "url": url,
                                    "method": req.get("method"),
                                    "post": (req.get("postData") or "")[:400],
                                }
                            )
                    elif m == "Network.responseReceived":
                        resp = p.get("response") or {}
                        url = resp.get("url") or ""
                        if any(k in url.lower() for k in ("pdf", "watermark", "standard", "upload", "bus", "cipher")):
                            events.append(
                                {
                                    "kind": "resp",
                                    "url": url,
                                    "status": resp.get("status"),
                                    "mime": resp.get("mimeType"),
                                }
                            )
                    continue
                if data.get("id") != current:
                    continue
                if "error" in data:
                    raise RuntimeError(data["error"])
                return data.get("result") or {}

        await call("Network.enable")
        await call("Page.enable")
        await call("Runtime.enable")
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

        setup_js = f"""
        (() => {{
          if (window.UrlUtils && window.UrlUtils.setPdfPreviewCookie) {{
            window.UrlUtils.setPdfPreviewCookie({json.dumps(uid)}, 'cn', 1);
            return {{ ok: true }};
          }}
          return {{ ok: false }};
        }})()
        """
        setup = await call("Runtime.evaluate", {"expression": setup_js, "returnByValue": True})
        await call("Page.navigate", {"url": f"{ORIGIN}/ms/pdf-preview"})
        await asyncio.sleep(12)

        state_js = """
        (() => ({
          href: location.href,
          title: document.title,
          text: (document.body && document.body.innerText || '').slice(0, 1200),
          embeds: [...document.querySelectorAll('iframe,embed,object,canvas,a')].slice(0, 20).map(el => ({
            tag: el.tagName,
            src: el.src || el.data || '',
            href: el.href || '',
          })),
        }))()
        """
        state = await call("Runtime.evaluate", {"expression": state_js, "returnByValue": True})
        return {
            "setup": (setup.get("result") or {}).get("value"),
            "state": (state.get("result") or {}).get("value"),
            "events": events,
        }


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    cdp = resolve_ttbz_cdp_url()
    cookies = fetch_ttbz_browser_cookies(cdp_url=cdp) if cdp else []

    async def runner() -> dict:
        return await run(uid, cookies)

    print(json.dumps(asyncio.run(runner()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
