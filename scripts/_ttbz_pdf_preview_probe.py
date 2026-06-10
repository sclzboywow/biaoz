"""Probe TTBZ /ms/pdf-preview flow and capture real PDF download."""

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

import httpx
import websockets

from app.http_proxy import resolve_ttbz_http_proxy
from app.ttbz_browser_session import apply_ttbz_browser_cookies, fetch_ttbz_browser_cookies, resolve_ttbz_cdp_url

ORIGIN = "https://www.ttbz.org.cn"
BUS = f"{ORIGIN}/cms-proxy/ms/bus/standardInfo"
PREVIEW = f"{ORIGIN}/ms/pdf-preview"


def build_pdf_preview_cookie(uid: str, *, lang: str = "cn", operate_type: int = 1) -> str:
    payload = json.dumps(
        {"mode": "api", "standardUniqueId": uid, "lang": lang, "type": operate_type},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    encoded = base64.b64encode(urllib.parse.quote(payload, safe="").encode("utf-8")).decode("ascii")
    return f"_pdf_preview={encoded}"


async def cdp_preview_probe(uid: str) -> dict:
    cdp_url = resolve_ttbz_cdp_url()
    if not cdp_url:
        raise RuntimeError("TTBZ_CDP_URL not set")
    pages = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
    target = pages[0]
    detail_url = f"{ORIGIN}/standardDetail/{uid}.html"
    events: list[dict] = []

    async with websockets.connect(target["webSocketDebuggerUrl"], max_size=32_000_000) as ws:
        msg_id = 1
        bodies: dict[str, dict] = {}

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
                        if any(k in url.lower() for k in ("pdf", "uploadfiles", "watermark", "standardinfo", "preview")):
                            events.append(
                                {
                                    "kind": "request",
                                    "url": url,
                                    "method": req.get("method"),
                                    "postData": req.get("postData"),
                                }
                            )
                    if m == "Network.responseReceived":
                        resp = p.get("response") or {}
                        url = resp.get("url") or ""
                        if any(k in url.lower() for k in ("pdf", "uploadfiles", "watermark", "standardinfo", "preview")):
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
                    if m == "Network.loadingFinished":
                        rid = p.get("requestId")
                        for ev in events:
                            if ev.get("requestId") == rid and ev.get("kind") == "response":
                                try:
                                    body = await call("Network.getResponseBody", {"requestId": rid})
                                    content = body.get("body") or ""
                                    if body.get("base64Encoded"):
                                        content_bytes = base64.b64decode(content)
                                    else:
                                        content_bytes = content.encode("latin-1", errors="ignore")
                                    bodies[rid] = {
                                        "size": len(content_bytes),
                                        "isPdf": content_bytes.startswith(b"%PDF"),
                                        "head": content_bytes[:80].decode("latin-1", errors="ignore"),
                                        "textHead": content[:200] if not content_bytes.startswith(b"%PDF") else "",
                                    }
                                except RuntimeError:
                                    pass
                    continue
                if data.get("id") != current:
                    continue
                if "error" in data:
                    raise RuntimeError(data["error"])
                return data.get("result") or {}

        await call("Page.enable")
        await call("Runtime.enable")
        await call("Network.enable")
        await call("Page.navigate", {"url": detail_url})
        await asyncio.sleep(5)

        click_js = """
        (async () => {
          if (window.UrlUtils && window.UrlUtils.openPdfPreview) {
            window.UrlUtils.openPdfPreview({
              mode: 'api',
              standardUniqueId: %s,
              lang: 'cn'
            });
            return { ok: true, via: 'UrlUtils.openPdfPreview' };
          }
          const btn = [...document.querySelectorAll('.action-item')].find(el => (el.innerText||'').includes('阅览'));
          if (btn) { btn.click(); return { ok: true, via: 'click' }; }
          return { ok: false };
        })()
        """ % json.dumps(uid)
        click = await call("Runtime.evaluate", {"expression": click_js, "awaitPromise": True, "returnByValue": True})
        await asyncio.sleep(8)

        pages_after = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
        preview_pages = [p for p in pages_after if "pdf-preview" in (p.get("url") or "")]
        preview_info: dict = {"pages": [p.get("url") for p in preview_pages]}

        if preview_pages:
            preview_ws = preview_pages[0]["webSocketDebuggerUrl"]
            async with websockets.connect(preview_ws, max_size=32_000_000) as pws:
                pid = 1

                async def pcall(method: str, params: dict | None = None) -> dict:
                    nonlocal pid
                    current = pid
                    pid += 1
                    await pws.send(json.dumps({"id": current, "method": method, "params": params or {}}))
                    while True:
                        data = json.loads(await pws.recv())
                        if data.get("id") != current:
                            continue
                        if "error" in data:
                            raise RuntimeError(data["error"])
                        return data.get("result") or {}

                await pcall("Runtime.enable")
                await pcall("Network.enable")
                await asyncio.sleep(4)
                state_js = """
                (() => {
                  const cookies = document.cookie;
                  const iframe = [...document.querySelectorAll('iframe,embed,object')].map(el => el.src || el.data || '');
                  const text = (document.body && document.body.innerText || '').slice(0, 500);
                  return { href: location.href, title: document.title, cookies, iframe, text };
                })()
                """
                state = await pcall("Runtime.evaluate", {"expression": state_js, "returnByValue": True})
                preview_info["state"] = (state.get("result") or {}).get("value")

        return {
            "click": (click.get("result") or {}).get("value"),
            "preview": preview_info,
            "network": events[-40:],
            "bodies": bodies,
        }


def httpx_preview_probe(uid: str) -> dict:
    ref = f"{ORIGIN}/standardDetail/{uid}.html"
    proxy = resolve_ttbz_http_proxy()
    kwargs: dict = {"timeout": 60, "follow_redirects": True, "headers": {"User-Agent": "Mozilla/5.0", "Referer": ref}}
    if proxy:
        kwargs["proxy"] = proxy
    out: dict = {}
    with httpx.Client(**kwargs) as client:
        apply_ttbz_browser_cookies(client, cdp_url=resolve_ttbz_cdp_url())
        client.cookies.set("_pdf_preview", build_pdf_preview_cookie(uid).split("=", 1)[1], domain=".ttbz.org.cn", path="/")
        preview = client.get(PREVIEW, headers={"Referer": ref})
        out["preview_page"] = {
            "status": preview.status_code,
            "size": len(preview.content),
            "head": (preview.text or "")[:300],
        }
        for payload in [
            {"operateType": "1", "standardUniqueId": uid, "fileLang": "cn"},
            {"operateType": 1, "standardUniqueId": uid, "fileLang": "cn"},
        ]:
            resp = client.post(
                f"{BUS}/getStdPdfWatermarked",
                data=payload,
                headers={"Referer": PREVIEW, "Accept": "application/json,application/pdf,*/*"},
            )
            key = f"watermarked_{payload['operateType']}"
            item = {
                "status": resp.status_code,
                "mime": resp.headers.get("content-type"),
                "size": len(resp.content),
                "isPdf": resp.content.startswith(b"%PDF"),
                "head": resp.content[:120].decode("latin-1", errors="ignore"),
            }
            if resp.headers.get("content-type", "").startswith("application/json"):
                try:
                    item["json"] = resp.json()
                except Exception:
                    pass
            out[key] = item
    return out


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    print("cookie", build_pdf_preview_cookie(uid))
    print("httpx", json.dumps(httpx_preview_probe(uid), ensure_ascii=False))
    print("cdp", json.dumps(asyncio.run(cdp_preview_probe(uid)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
