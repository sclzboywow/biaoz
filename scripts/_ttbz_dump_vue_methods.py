"""Dump TTBZ Vue PDF method sources to log file."""

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

from app.ttbz_browser_session import resolve_ttbz_cdp_url

ORIGIN = "https://www.ttbz.org.cn"


async def main(uid: str, out_path: Path) -> None:
    cdp_url = resolve_ttbz_cdp_url()
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
        await call("Page.navigate", {"url": detail_url})
        await asyncio.sleep(6)
        js = """
        (() => {
          function findDetailVm() {
            const app = document.querySelector('#app');
            const stack = app && app.__vue__ ? [app.__vue__] : [];
            while (stack.length) {
              const vm = stack.pop();
              if (!vm) continue;
              const methods = vm.$options && vm.$options.methods ? Object.keys(vm.$options.methods) : [];
              if (methods.includes('getWatermarkedPdf')) return vm;
              if (vm.$children) stack.push(...vm.$children);
            }
            return null;
          }
          const vm = findDetailVm();
          if (!vm) return { error: 'no vm' };
          const out = {};
          for (const name of ['getWatermarkedPdf', 'setPdfPreviewCookie', 'preview', 'downloadFile']) {
            const fn = vm.$options.methods[name];
            out[name] = fn ? String(fn) : null;
          }
          return out;
        })()
        """
        result = await call("Runtime.evaluate", {"expression": js, "returnByValue": True})
        value = (result.get("result") or {}).get("value") or {}
        out_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    out = ROOT / "logs" / "ttbz-vue-methods.json"
    asyncio.run(main(uid, out))
    print(str(out))
