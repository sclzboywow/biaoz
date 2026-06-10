"""Scan TTBZ standards until getWatermarkedPdf succeeds in browser."""

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

import httpx
import websockets

from app.http_proxy import resolve_ttbz_http_proxy
from app.ttbz_browser_session import apply_ttbz_browser_cookies, resolve_ttbz_cdp_url

ORIGIN = "https://www.ttbz.org.cn"
PORTAL = "https://www.ttbz.org.cn/cms-proxy/ms/portal/standardInfo"
BUS = "https://www.ttbz.org.cn/cms-proxy/ms/bus/standardInfo"


async def vm_probe(uid: str) -> dict:
    cdp_url = resolve_ttbz_cdp_url()
    pages = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
    target = pages[0]
    detail_url = f"{ORIGIN}/standardDetail/{uid}.html"
    async with websockets.connect(target["webSocketDebuggerUrl"], max_size=8_000_000) as ws:
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
          try {
            if (typeof vm.setPdfPreviewCookie === 'function') await vm.setPdfPreviewCookie();
            const ret = await vm.getWatermarkedPdf();
            if (typeof ret === 'string') {
              return { ok: ret.startsWith('data:application/pdf') || ret.includes('/UploadFiles/'), retHead: ret.slice(0, 120) };
            }
            return { ok: true, retKeys: ret && typeof ret === 'object' ? Object.keys(ret) : [], ret };
          } catch (err) {
            return { ok: false, error: String(err) };
          }
        })()
        """
        result = await call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
        return (result.get("result") or {}).get("value") or {}


def main() -> int:
    page_no = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    proxy = resolve_ttbz_http_proxy()
    kwargs: dict = {"timeout": 60, "follow_redirects": True, "headers": {"User-Agent": "Mozilla/5.0", "Referer": f"{ORIGIN}/standard.html"}}
    if proxy:
        kwargs["proxy"] = proxy
    with httpx.Client(**kwargs) as client:
        apply_ttbz_browser_cookies(client, cdp_url=resolve_ttbz_cdp_url())
        rows = client.post(f"{PORTAL}/getPortalStandardList", data={"pageNo": page_no, "pageSize": limit, "isOpen": "1"}).json()["data"]["rows"]
        for row in rows:
            uid = row["standardUniqueId"]
            no = row.get("standardNo")
            detail = client.post(f"{PORTAL}/getPortalStandardById", data={"standardUniqueId": uid}).json().get("data") or {}
            vm = asyncio.run(vm_probe(uid))
            print(json.dumps({"standardNo": no, "uid": uid, "publishDate": detail.get("publishDate"), "hasCnPdf": detail.get("hasCnPdf"), "standardPdfUrl": detail.get("standardPdfUrl"), "files": detail.get("files"), "vm": vm}, ensure_ascii=False))
            if vm.get("ok"):
                print("FOUND_REAL_PDF", no, uid)
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
