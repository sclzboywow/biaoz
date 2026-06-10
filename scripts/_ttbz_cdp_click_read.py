"""Click TTBZ detail page '阅览中文版' via CDP and capture PDF download."""

from __future__ import annotations

import asyncio
import base64
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

from app.ttbz_browser_session import resolve_ttbz_cdp_url

ORIGIN = "https://www.ttbz.org.cn"


def pick_target(cdp_url: str) -> dict:
    pages = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
    for page in pages:
        if page.get("type") == "page":
            return page
    raise RuntimeError("no CDP page")


async def click_read_cn(uid: str) -> dict:
    cdp_url = resolve_ttbz_cdp_url()
    if not cdp_url:
        raise RuntimeError("TTBZ_CDP_URL not set")
    target = pick_target(cdp_url)
    detail_url = f"{ORIGIN}/standardDetail/{uid}.html"
    ws_url = target["webSocketDebuggerUrl"]
    events: list[dict] = []

    async with websockets.connect(ws_url, max_size=16_000_000) as ws:
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
                    events.append(data)
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
        (() => {
          const nodes = [...document.querySelectorAll('a,button,span,div,p,li')];
          const hit = nodes.find(el => (el.innerText || '').trim() === '阅览中文版');
          if (!hit) {
            return { clicked: false, candidates: nodes
              .map(el => (el.innerText || '').trim())
              .filter(t => /阅览|PDF|全文|下载|中文/i.test(t))
              .slice(0, 20) };
          }
          hit.click();
          return { clicked: true, tag: hit.tagName, text: (hit.innerText || '').trim() };
        })()
        """
        click_result = await call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
        click_value = (click_result.get("result") or {}).get("value") or {}
        await asyncio.sleep(6)

        pages = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
        page_urls = [p.get("url") for p in pages if p.get("type") == "page"]

        req_hits = []
        for ev in events:
            method = ev.get("method")
            params = ev.get("params") or {}
            if method == "Network.responseReceived":
                resp = params.get("response") or {}
                url = resp.get("url") or ""
                mime = resp.get("mimeType") or ""
                if any(k in url.lower() for k in ("uploadfiles", "download", "pdf", "standardinfo")) or "pdf" in mime:
                    req_hits.append(
                        {
                            "url": url,
                            "mime": mime,
                            "status": resp.get("status"),
                        }
                    )
            if method == "Network.requestWillBeSent":
                req = params.get("request") or {}
                url = req.get("url") or ""
                if any(k in url.lower() for k in ("uploadfiles", "download", "pdf", "standardinfo")):
                    req_hits.append({"request": url, "method": req.get("method")})

        pdf_fetch_js = """
        (async () => {
          const reqs = performance.getEntriesByType('resource')
            .map(e => ({name: e.name, type: e.initiatorType}))
            .filter(e => /uploadfiles|download|pdf|standardinfo/i.test(e.name));
          return { reqs: reqs.slice(-20), href: location.href, title: document.title };
        })()
        """
        perf = await call("Runtime.evaluate", {"expression": pdf_fetch_js, "awaitPromise": True, "returnByValue": True})
        perf_value = (perf.get("result") or {}).get("value") or {}

        return {
            "detail_url": detail_url,
            "click": click_value,
            "page_urls": page_urls,
            "network_hits": req_hits[-30:],
            "perf": perf_value,
        }


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    result = asyncio.run(click_read_cn(uid))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
