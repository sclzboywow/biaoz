"""Call TTBZ Vue getWatermarkedPdf and return PDF metadata."""

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

import httpx
import websockets

from app.http_proxy import resolve_ttbz_http_proxy
from app.ttbz_browser_session import apply_ttbz_browser_cookies, resolve_ttbz_cdp_url

ORIGIN = "https://www.ttbz.org.cn"
BUS_API = "https://www.ttbz.org.cn/cms-proxy/ms/bus/standardInfo"


async def browser_get_pdf(uid: str) -> dict:
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
        await call("Page.navigate", {"url": detail_url})
        await asyncio.sleep(6)

        js = """
        (async () => {
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
          if (!vm) return { error: 'vm not found' };
          if (typeof vm.setPdfPreviewCookie === 'function') {
            try { await vm.setPdfPreviewCookie(); } catch (e) { /* ignore */ }
          }
          let ret = null;
          try {
            ret = await vm.getWatermarkedPdf();
          } catch (err) {
            return { error: String(err) };
          }
          const out = { retType: typeof ret };
          if (typeof ret === 'string') {
            out.retHead = ret.slice(0, 200);
            out.isPdfDataUrl = ret.startsWith('data:application/pdf');
          } else if (ret && typeof ret === 'object') {
            out.retKeys = Object.keys(ret);
            for (const k of ['url', 'pdfUrl', 'fileUrl', 'data', 'blob', 'message', 'msg', 'code']) {
              if (ret[k] !== undefined) out[k] = ret[k];
            }
          }
          return out;
        })()
        """
        result = await call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
        return (result.get("result") or {}).get("value") or {}


def httpx_post(uid: str, endpoint: str, payload: dict[str, str]) -> dict:
    ref = f"{ORIGIN}/standardDetail/{uid}.html"
    proxy = resolve_ttbz_http_proxy()
    kwargs: dict = {"timeout": 60, "follow_redirects": True, "headers": {"User-Agent": "Mozilla/5.0", "Referer": ref}}
    if proxy:
        kwargs["proxy"] = proxy
    with httpx.Client(**kwargs) as client:
        apply_ttbz_browser_cookies(client, cdp_url=resolve_ttbz_cdp_url())
        resp = client.post(
            f"{BUS_API}/{endpoint}",
            data=payload,
            headers={"Accept": "application/pdf,application/json,*/*", "Referer": ref},
        )
        head = resp.content[:160].decode("latin-1", errors="ignore")
        body_json = None
        if resp.headers.get("content-type", "").startswith("application/json"):
            try:
                body_json = resp.json()
            except Exception:
                body_json = None
        return {
            "status": resp.status_code,
            "mime": resp.headers.get("content-type"),
            "size": len(resp.content),
            "isPdf": resp.content.startswith(b"%PDF"),
            "head": head,
            "json": body_json,
            "payload": payload,
        }


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    browser = asyncio.run(browser_get_pdf(uid))
    print("browser", json.dumps(browser, ensure_ascii=False))
    for endpoint, payload in [
        ("getStdPdfWatermarked", {"standardUniqueId": uid}),
        ("getStdPdfWatermarked", {"standardUniqueId": uid, "type": "1"}),
        ("getStdPdfWatermarked", {"standardUniqueId": uid, "lang": "cn"}),
    ]:
        print(endpoint, json.dumps(httpx_post(uid, endpoint, payload), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
