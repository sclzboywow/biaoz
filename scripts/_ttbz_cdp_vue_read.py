"""Inspect Vue handlers for TTBZ 阅览中文版."""

from __future__ import annotations

import asyncio
import json
import os
import re
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


async def main(uid: str) -> int:
    cdp_url = resolve_ttbz_cdp_url()
    if not cdp_url:
        raise RuntimeError("TTBZ_CDP_URL not set")
    pages = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
    target = pages[0]
    detail_url = f"{ORIGIN}/standardDetail/{uid}.html"

    async with websockets.connect(target["webSocketDebuggerUrl"], max_size=16_000_000) as ws:
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
        await call("Network.enable")
        await call("Page.navigate", {"url": detail_url})
        await asyncio.sleep(6)

        html = (await call("Runtime.evaluate", {"expression": "document.documentElement.outerHTML", "returnByValue": True}))
        html_text = (html.get("result") or {}).get("value") or ""
        for pat in ["viewCn", "阅览", "downLoadStandard", "standardPdfUrl", "preview", "online", "readStandard", "openPdf"]:
            print("pat", pat, html_text.count(pat))
        for match in re.finditer(r".{0,60}viewCn.{0,120}", html_text):
            print("viewCn ctx", match.group(0).replace("\n", " ")[:220])

        vue_js = """
        (() => {
          function walk(vm, out) {
            if (!vm || out.length > 200) return;
            const methods = vm.$options && vm.$options.methods ? Object.keys(vm.$options.methods) : [];
            for (const name of methods) {
              if (/view|read|pdf|download|cn|preview|file/i.test(name)) out.push(name);
            }
            if (vm.$children) vm.$children.forEach(child => walk(child, out));
          }
          const app = document.querySelector('#app');
          const vm = app && app.__vue__;
          const hits = [];
          walk(vm, hits);
          return { hits: [...new Set(hits)] };
        })()
        """
        vue = await call("Runtime.evaluate", {"expression": vue_js, "returnByValue": True})
        print("vue", json.dumps((vue.get("result") or {}).get("value"), ensure_ascii=False))

        click_and_capture = """
        (async () => {
          const events = [];
          const oldFetch = window.fetch;
          window.fetch = async (...args) => {
            events.push({ kind: 'fetch', url: String(args[0]) });
            return oldFetch(...args);
          };
          const oldOpen = XMLHttpRequest.prototype.open;
          XMLHttpRequest.prototype.open = function(method, url, ...rest) {
            events.push({ kind: 'xhr', method, url: String(url) });
            return oldOpen.call(this, method, url, ...rest);
          };
          const btn = [...document.querySelectorAll('.action-item')].find(el => (el.innerText||'').includes('阅览'));
          if (!btn) return { clicked: false, events };
          btn.click();
          await new Promise(r => setTimeout(r, 3000));
          return {
            clicked: true,
            events,
            dialogs: [...document.querySelectorAll('.el-dialog__wrapper')].map(el => ({
              cls: el.className,
              display: el.style.display,
              text: (el.innerText||'').slice(0,200)
            })),
            iframe: [...document.querySelectorAll('iframe')].map(el => el.src),
          };
        })()
        """
        cap = await call("Runtime.evaluate", {"expression": click_and_capture, "awaitPromise": True, "returnByValue": True})
        print("capture", json.dumps((cap.get("result") or {}).get("value"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    raise SystemExit(asyncio.run(main(uid)))
