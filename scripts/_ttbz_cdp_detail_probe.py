"""Navigate TTBZ detail page via CDP and extract download UI hints."""

from __future__ import annotations

import asyncio
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

from app.ttbz_browser_session import resolve_ttbz_cdp_url

ORIGIN = "https://www.ttbz.org.cn"


def pick_target(cdp_url: str) -> dict:
    pages = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
    for page in pages:
        if page.get("type") == "page":
            return page
    raise RuntimeError("no CDP page")


async def probe_detail_page(uid: str) -> dict:
    cdp_url = resolve_ttbz_cdp_url()
    if not cdp_url:
        raise RuntimeError("TTBZ_CDP_URL not set")
    target = pick_target(cdp_url)
    detail_url = f"{ORIGIN}/standardDetail/{uid}.html"
    ws_url = target["webSocketDebuggerUrl"]

    async with websockets.connect(ws_url, max_size=8_000_000) as ws:
        msg_id = 1

        async def call(method: str, params: dict | None = None) -> dict:
            nonlocal msg_id
            current = msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": current, "method": method, "params": params or {}}))
            while True:
                data = json.loads(await ws.recv())
                if data.get("id") != current:
                    continue
                if "error" in data:
                    raise RuntimeError(data["error"])
                return data.get("result") or {}

        await call("Page.enable")
        await call("Runtime.enable")
        await call("Page.navigate", {"url": detail_url})
        await asyncio.sleep(4)
        js = """
        (() => {
          const text = document.body ? document.body.innerText : '';
          const links = [...document.querySelectorAll('a[href],button,span,div')]
            .map(el => ({tag: el.tagName, text: (el.innerText||'').trim().slice(0,80), href: el.getAttribute('href')||''}))
            .filter(x => /下载|PDF|全文|标准文本|公告|登录|身份|会员|购买/i.test(x.text + x.href));
          const scripts = [...document.scripts].map(s => s.src || s.textContent.slice(0,200));
          return {
            title: document.title,
            url: location.href,
            text_snip: text.slice(0, 1500),
            links: links.slice(0, 30),
            script_hits: scripts.filter(s => /downLoad|standardPdf|UploadFiles|fileType/i.test(s)).slice(0, 10),
          };
        })()
        """
        result = await call("Runtime.evaluate", {"expression": js, "returnByValue": True})
        value = (result.get("result") or {}).get("value")
        if not isinstance(value, dict):
            raise RuntimeError(repr(value))
        return value


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    print(json.dumps(asyncio.run(probe_detail_page(uid)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
