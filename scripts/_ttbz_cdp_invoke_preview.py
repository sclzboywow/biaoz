"""Invoke TTBZ Vue preview/download methods via CDP."""

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


async def invoke(uid: str) -> dict:
    cdp_url = resolve_ttbz_cdp_url()
    if not cdp_url:
        raise RuntimeError("TTBZ_CDP_URL not set")
    pages = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
    target = pages[0]
    detail_url = f"{ORIGIN}/standardDetail/{uid}.html"
    events: list[dict] = []

    async with websockets.connect(target["webSocketDebuggerUrl"], max_size=16_000_000) as ws:
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
        await asyncio.sleep(6)

        js = """
        (async () => {
          function findDetailVm() {
            const app = document.querySelector('#app');
            const stack = app && app.__vue__ ? [app.__vue__] : [];
            const out = [];
            while (stack.length) {
              const vm = stack.pop();
              if (!vm) continue;
              const methods = vm.$options && vm.$options.methods ? Object.keys(vm.$options.methods) : [];
              if (methods.includes('preview') || methods.includes('previewFile')) out.push(vm);
              if (vm.$children) stack.push(...vm.$children);
            }
            return out[0] || null;
          }
          const vm = findDetailVm();
          if (!vm) return { error: 'detail vm not found' };
          const calls = {};
          const tryCall = async (name) => {
            try {
              const fn = vm[name];
              if (typeof fn !== 'function') return { ok: false, reason: 'missing' };
              const ret = fn.call(vm);
              if (ret && typeof ret.then === 'function') await ret;
              return { ok: true };
            } catch (err) {
              return { ok: false, error: String(err) };
            }
          };
          calls.preview = await tryCall('preview');
          await new Promise(r => setTimeout(r, 2000));
          calls.previewFile = await tryCall('previewFile');
          await new Promise(r => setTimeout(r, 2000));
          calls.download = await tryCall('download');
          await new Promise(r => setTimeout(r, 2000));
          calls.downloadFile = await tryCall('downloadFile');
          return {
            dataKeys: vm.standardInfo ? Object.keys(vm.standardInfo).filter(k => /pdf|file|url/i.test(k)) : [],
            standardInfo: vm.standardInfo ? {
              standardPdfUrl: vm.standardInfo.standardPdfUrl,
              hasCnPdf: vm.standardInfo.hasCnPdf,
              files: vm.standardInfo.files,
            } : null,
            calls,
            href: location.href,
            dialogs: [...document.querySelectorAll('.el-dialog__wrapper')].map(el => ({
              cls: el.className,
              display: el.style.display,
              text: (el.innerText || '').slice(0, 300),
            })),
            iframes: [...document.querySelectorAll('iframe,embed,object')].map(el => el.src || el.data || ''),
          };
        })()
        """
        result = await call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
        value = (result.get("result") or {}).get("value") or {}

        hits = []
        for ev in events:
            method = ev.get("method")
            params = ev.get("params") or {}
            if method == "Network.responseReceived":
                resp = params.get("response") or {}
                url = resp.get("url") or ""
                if any(k in url.lower() for k in ("uploadfiles", "download", "pdf", "standardinfo", "preview", "watermark")):
                    hits.append({"url": url, "mime": resp.get("mimeType"), "status": resp.get("status")})
            if method == "Network.requestWillBeSent":
                req = params.get("request") or {}
                url = req.get("url") or ""
                if any(k in url.lower() for k in ("uploadfiles", "download", "pdf", "standardinfo", "preview", "watermark")):
                    hits.append({"request": url, "method": req.get("method")})
        value["network_hits"] = hits[-40:]
        return value


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    print(json.dumps(asyncio.run(invoke(uid)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
