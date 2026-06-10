"""Probe TTBZ PDF download via CDP in-browser fetch (uses real browser session)."""

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
from app.ttbz_browser_session import fetch_ttbz_browser_cookies, resolve_ttbz_cdp_url

API = "https://www.ttbz.org.cn/cms-proxy/ms/portal/standardInfo"
ORIGIN = "https://www.ttbz.org.cn"


def pick_target(cdp_url: str) -> dict:
    pages = json.loads(urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=10).read())
    for page in pages:
        if page.get("type") == "page" and "ttbz.org.cn" in (page.get("url") or ""):
            return page
    for page in pages:
        if page.get("type") == "page":
            return page
    raise RuntimeError("no CDP page target")


async def browser_probe(uid: str) -> dict:
    cdp_url = resolve_ttbz_cdp_url()
    if not cdp_url:
        raise RuntimeError("TTBZ_CDP_URL not set")
    target = pick_target(cdp_url)
    ref = f"{ORIGIN}/standardDetail/{uid}.html"
    js = f"""
    (async () => {{
      try {{
        const uid = {json.dumps(uid)};
        const ref = {json.dumps(ref)};
        const detailResp = await fetch("{API}/getPortalStandardById", {{
          method: "POST",
          headers: {{"Content-Type": "application/x-www-form-urlencoded", "Referer": ref}},
          body: new URLSearchParams({{ standardUniqueId: uid }}),
        }});
        const detailText = await detailResp.text();
        let detailJson = null;
        try {{ detailJson = JSON.parse(detailText); }} catch (e) {{}}
        const dlResp = await fetch("{API}/downLoadStandard", {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/pdf,*/*",
            "Referer": ref,
          }},
          body: new URLSearchParams({{ standardUniqueId: uid }}),
        }});
        const buf = new Uint8Array(await dlResp.arrayBuffer());
        let head = "";
        for (let i = 0; i < Math.min(120, buf.length); i++) head += String.fromCharCode(buf[i]);
        const data = detailJson?.data || {{}};
        return {{
          cdp_page: document.location.href,
          detailStatus: detailResp.status,
          detailHead: detailText.slice(0, 120),
          standardPdfUrl: data.standardPdfUrl,
          hasCnPdf: data.hasCnPdf,
          files: (data.files || []).map((f) => ({{
            t: f.fileType,
            n: f.fileTypeName,
            o: f.originalFileName,
            u: f.fileUrl,
          }})),
          dlStatus: dlResp.status,
          dlType: dlResp.headers.get("content-type"),
          dlSize: buf.length,
          isPdf: head.startsWith("%PDF"),
          head,
        }};
      }} catch (err) {{
        return {{ error: String(err), stack: err && err.stack ? err.stack : null, cdp_page: document.location.href }};
      }}
    }})()
    """
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

        await call("Runtime.enable")
        result = await call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
        inner = result.get("result") or {}
        if inner.get("exceptionDetails"):
            raise RuntimeError(inner["exceptionDetails"])
        value = inner.get("value")
        print("cdp_raw", json.dumps(inner, ensure_ascii=False)[:2000], flush=True)
        if value is None:
            raise RuntimeError(f"evaluate returned null: {inner!r}")
        if not isinstance(value, dict):
            raise RuntimeError(f"unexpected evaluate result: {value!r}")
        value["target_url"] = target.get("url")
        return value


def httpx_probe(uid: str) -> dict:
    ref = f"{ORIGIN}/standardDetail/{uid}.html"
    proxy = resolve_ttbz_http_proxy()
    kwargs: dict = {
        "timeout": 60,
        "follow_redirects": True,
        "headers": {"User-Agent": "Mozilla/5.0", "Referer": ref},
    }
    if proxy:
        kwargs["proxy"] = proxy
    with httpx.Client(**kwargs) as client:
        for item in fetch_ttbz_browser_cookies():
            name = str(item.get("name") or "")
            value = str(item.get("value") or "")
            if not name:
                continue
            domain = str(item.get("domain") or ".ttbz.org.cn")
            if not domain.startswith("."):
                domain = f".{domain}"
            client.cookies.set(name, value, domain=domain, path=str(item.get("path") or "/"))
        detail_resp = client.post(f"{API}/getPortalStandardById", data={"standardUniqueId": uid})
        if detail_resp.status_code != 200 or not detail_resp.text.strip().startswith("{"):
            return {
                "detailStatus": detail_resp.status_code,
                "detailHead": (detail_resp.text or "")[:120],
            }
        detail = detail_resp.json().get("data") or {}
        dl = client.post(
            f"{API}/downLoadStandard",
            data={"standardUniqueId": uid},
            headers={"Accept": "application/pdf,*/*", "Referer": ref},
        )
        head = dl.content[:120].decode("latin-1", errors="ignore")
        return {
            "standardPdfUrl": detail.get("standardPdfUrl"),
            "hasCnPdf": detail.get("hasCnPdf"),
            "files": detail.get("files"),
            "dlStatus": dl.status_code,
            "dlSize": len(dl.content),
            "isPdf": dl.content.startswith(b"%PDF"),
            "head": head,
        }


def main() -> int:
    uid = sys.argv[1] if len(sys.argv) > 1 else "3ae673d9d59441b59a5fb3f57838cd02"
    cookies = fetch_ttbz_browser_cookies()
    print("cookies", json.dumps([c.get("name") for c in cookies], ensure_ascii=False))
    print("httpx", json.dumps(httpx_probe(uid), ensure_ascii=False))
    print("cdp", json.dumps(asyncio.run(browser_probe(uid)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
