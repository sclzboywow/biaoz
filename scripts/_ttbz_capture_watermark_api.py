"""Capture getStdPdfWatermarked request/response via CDP."""

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
from app.ttbz_browser_session import apply_ttbz_browser_cookies, fetch_ttbz_browser_cookies, resolve_ttbz_cdp_url

ORIGIN = "https://www.ttbz.org.cn"
BUS_API = "https://www.ttbz.org.cn/cms-proxy/ms/bus/standardInfo"


async def capture(uid: str) -> dict:
    cdp_url = resolve_ttbz_cdp_url()
    if not cdp_url:
        raise RuntimeError("TTBZ_CDP_URL not set")
    pages = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
    target = pages[0]
    detail_url = f"{ORIGIN}/standardDetail/{uid}.html"
    captured: dict = {}

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
                    m = data["method"]
                    p = data.get("params") or {}
                    if m == "Network.requestWillBeSent":
                        req = p.get("request") or {}
                        url = req.get("url") or ""
                        if "getStdPdfWatermarked" in url:
                            headers = dict(req.get("headers") or {})
                            for key in list(headers):
                                if key.lower() in {"cookie", "authorization", "x-auth-token"}:
                                    headers[key] = "<redacted>"
                            captured["request"] = {
                                "url": url,
                                "method": req.get("method"),
                                "headers": headers,
                                "postData": req.get("postData"),
                            }
                    if m == "Network.responseReceived":
                        resp = p.get("response") or {}
                        url = resp.get("url") or ""
                        if "getStdPdfWatermarked" in url:
                            captured["response"] = {
                                "url": url,
                                "status": resp.get("status"),
                                "mime": resp.get("mimeType"),
                                "requestId": p.get("requestId"),
                            }
                    if m == "Network.loadingFinished" and captured.get("response", {}).get("requestId") == p.get("requestId"):
                        body = await call("Network.getResponseBody", {"requestId": p.get("requestId")})
                        content = body.get("body") or ""
                        if body.get("base64Encoded"):
                            content_bytes = base64.b64decode(content)
                        else:
                            content_bytes = content.encode("latin-1", errors="ignore")
                        captured["body"] = {
                            "size": len(content_bytes),
                            "isPdf": content_bytes.startswith(b"%PDF"),
                            "head": content_bytes[:120].decode("latin-1", errors="ignore"),
                            "textHead": content[:200] if not content_bytes.startswith(b"%PDF") else "",
                        }
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
            while (stack.length) {
              const vm = stack.pop();
              if (!vm) continue;
              const methods = vm.$options && vm.$options.methods ? Object.keys(vm.$options.methods) : [];
              if (methods.includes('preview')) return vm;
              if (vm.$children) stack.push(...vm.$children);
            }
            return null;
          }
          const vm = findDetailVm();
          if (!vm) return { error: 'vm not found' };
          await vm.preview();
          return { ok: true };
        })()
        """
        await call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
        await asyncio.sleep(3)
    return captured


def httpx_try(uid: str, post_data: str | None) -> dict:
    ref = f"{ORIGIN}/standardDetail/{uid}.html"
    proxy = resolve_ttbz_http_proxy()
    kwargs: dict = {"timeout": 60, "follow_redirects": True, "headers": {"User-Agent": "Mozilla/5.0", "Referer": ref}}
    if proxy:
        kwargs["proxy"] = proxy
    with httpx.Client(**kwargs) as client:
        apply_ttbz_browser_cookies(client, cdp_url=resolve_ttbz_cdp_url())
        data = post_data or f"standardUniqueId={uid}"
        if "=" in data and "&" not in data and not data.startswith("{"):
            payload = dict(x.split("=", 1) for x in data.split("&"))
        else:
            payload = {"standardUniqueId": uid}
        resp = client.post(
            f"{BUS_API}/getStdPdfWatermarked",
            data=payload,
            headers={"Accept": "application/pdf,*/*", "Referer": ref, "Content-Type": "application/x-www-form-urlencoded"},
        )
        head = resp.content[:120].decode("latin-1", errors="ignore")
        return {
            "status": resp.status_code,
            "mime": resp.headers.get("content-type"),
            "size": len(resp.content),
            "isPdf": resp.content.startswith(b"%PDF"),
            "head": head,
            "payload": payload,
        }


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    captured = asyncio.run(capture(uid))
    print("captured", json.dumps({k: v for k, v in captured.items() if k != "body"}, ensure_ascii=False))
    if "body" in captured:
        print("body", json.dumps(captured["body"], ensure_ascii=False))
    post_data = (captured.get("request") or {}).get("postData")
    print("httpx", json.dumps(httpx_try(uid, post_data), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
