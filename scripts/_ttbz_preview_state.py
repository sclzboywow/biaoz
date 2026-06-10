"""Load TTBZ pdf-preview in browser and inspect viewer state + network."""

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


def preview_cookie(uid: str) -> str:
    payload = json.dumps({"mode": "api", "standardUniqueId": uid, "lang": "cn", "type": 1}, separators=(",", ":"))
    return base64.b64encode(urllib.parse.quote(payload, safe="").encode()).decode()


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
                    if m in {"Network.requestWillBeSent", "Network.responseReceived"}:
                        if m == "Network.requestWillBeSent":
                            req = p.get("request") or {}
                            events.append({"kind": "req", "url": req.get("url"), "method": req.get("method"), "post": (req.get("postData") or "")[:300]})
                        else:
                            resp = p.get("response") or {}
                            events.append({"kind": "resp", "url": resp.get("url"), "status": resp.get("status"), "mime": resp.get("mimeType")})
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
        await call(
            "Network.setCookie",
            {"name": "_pdf_preview", "value": preview_cookie(uid), "domain": "www.ttbz.org.cn", "path": "/"},
        )
        await call("Page.navigate", {"url": f"{ORIGIN}/ms/pdf-preview"})
        await asyncio.sleep(12)
        state = await call(
            "Runtime.evaluate",
            {
                "expression": """
                (() => {
                  const out = {
                    href: location.href,
                    title: document.title,
                    text: (document.body && document.body.innerText || '').slice(0, 1000),
                    embeds: [...document.querySelectorAll('iframe,embed,object,canvas,a')].slice(0,20).map(el => ({
                      tag: el.tagName,
                      src: el.src || el.data || '',
                      href: el.href || '',
                      text: (el.innerText||'').slice(0,80)
                    })),
                  };
                  return out;
                })()
                """,
                "returnByValue": True,
            },
        )
        return {
            "state": (state.get("result") or {}).get("value"),
            "events": [e for e in events if e.get("url") and any(k in e["url"].lower() for k in ("pdf", "watermark", "standard", "upload", "bus", "cipher", "static/js/pdf-preview"))][-50:],
            "all_count": len(events),
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
