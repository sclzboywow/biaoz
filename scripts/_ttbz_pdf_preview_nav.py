"""Navigate TTBZ pdf-preview with _pdf_preview cookie and capture PDF API."""

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
PREVIEW = f"{ORIGIN}/ms/pdf-preview"


def build_pdf_preview_cookie_value(uid: str) -> str:
    payload = json.dumps(
        {"mode": "api", "standardUniqueId": uid, "lang": "cn", "type": 1},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return base64.b64encode(urllib.parse.quote(payload, safe="").encode("utf-8")).decode("ascii")


async def probe(uid: str, browser_cookies: list[dict]) -> dict:
    cdp_url = resolve_ttbz_cdp_url()
    if not cdp_url:
        raise RuntimeError("TTBZ_CDP_URL not set")
    pages = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
    target = pages[0]
    events: list[dict] = []
    bodies: dict[str, dict] = {}

    async with websockets.connect(target["webSocketDebuggerUrl"], max_size=32_000_000) as ws:
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
                        events.append(
                            {
                                "kind": "request",
                                "url": url,
                                "method": req.get("method"),
                                "postData": (req.get("postData") or "")[:500],
                            }
                        )
                    elif m == "Network.responseReceived":
                        resp = p.get("response") or {}
                        url = resp.get("url") or ""
                        rid = p.get("requestId")
                        events.append(
                            {
                                "kind": "response",
                                "url": url,
                                "status": resp.get("status"),
                                "mime": resp.get("mimeType"),
                                "requestId": rid,
                            }
                        )
                    elif m == "Network.loadingFinished":
                        rid = p.get("requestId")
                        for ev in events:
                            if ev.get("requestId") == rid and ev.get("kind") == "response":
                                mime = ev.get("mime") or ""
                                if "pdf" in mime or any(
                                    k in (ev.get("url") or "").lower()
                                    for k in ("watermark", "uploadfiles", "standardinfo", "pdf")
                                ):
                                    try:
                                        body = await call("Network.getResponseBody", {"requestId": rid})
                                        content = body.get("body") or ""
                                        if body.get("base64Encoded"):
                                            content_bytes = base64.b64decode(content)
                                        else:
                                            content_bytes = content.encode("latin-1", errors="ignore")
                                        bodies[rid] = {
                                            "url": ev.get("url"),
                                            "size": len(content_bytes),
                                            "isPdf": content_bytes.startswith(b"%PDF"),
                                            "head": content_bytes[:100].decode("latin-1", errors="ignore"),
                                            "textHead": content[:300] if not content_bytes.startswith(b"%PDF") else "",
                                        }
                                    except RuntimeError:
                                        pass
                    continue
                if data.get("id") != current:
                    continue
                if "error" in data:
                    raise RuntimeError(data["error"])
                return data.get("result") or {}

        await call("Network.enable")
        await call("Page.enable")
        await call("Runtime.enable")

        for item in browser_cookies:
            name = str(item.get("name") or "")
            value = str(item.get("value") or "")
            if not name:
                continue
            await call(
                "Network.setCookie",
                {
                    "name": name,
                    "value": value,
                    "domain": str(item.get("domain") or ".ttbz.org.cn").lstrip("."),
                    "path": str(item.get("path") or "/"),
                    "secure": bool(item.get("secure")),
                    "httpOnly": bool(item.get("httpOnly")),
                },
            )
        await call(
            "Network.setCookie",
            {
                "name": "_pdf_preview",
                "value": build_pdf_preview_cookie_value(uid),
                "domain": "www.ttbz.org.cn",
                "path": "/",
                "secure": False,
                "httpOnly": False,
            },
        )

        await call("Page.navigate", {"url": PREVIEW})
        await asyncio.sleep(8)

        state_js = """
        (() => {
          const scripts = [...document.scripts].map(s => s.src).filter(Boolean);
          const text = (document.body && document.body.innerText || '').slice(0, 800);
          return {
            href: location.href,
            title: document.title,
            cookie: document.cookie,
            scripts,
            text,
          };
        })()
        """
        state = await call("Runtime.evaluate", {"expression": state_js, "returnByValue": True})
        return {
            "state": (state.get("result") or {}).get("value"),
            "events": events,
            "bodies": bodies,
        }


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    cdp_url = resolve_ttbz_cdp_url()
    browser_cookies = fetch_ttbz_browser_cookies(cdp_url=cdp_url) if cdp_url else []

    async def run() -> dict:
        return await probe(uid, browser_cookies)

    result = asyncio.run(run())
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
