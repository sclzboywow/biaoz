from __future__ import annotations

import asyncio
import base64
import json
import os
import urllib.parse
import urllib.request
from typing import Any

import httpx
import websockets

from app.http_proxy import resolve_ttbz_http_proxy

TTBZ_ORIGIN = "https://www.ttbz.org.cn"
TTBZ_BUS_API = "https://www.ttbz.org.cn/cms-proxy/ms/bus/standardInfo"
DEFAULT_TTBZ_CDP_URL = "http://127.0.0.1:9223"
_ACCESS_TOKEN_STORAGE_SUFFIX = "-accessToken"


class TtbzBrowserSessionError(RuntimeError):
    pass


def resolve_ttbz_cdp_url(value: str | None = None) -> str | None:
    resolved = (value or os.getenv("TTBZ_CDP_URL") or DEFAULT_TTBZ_CDP_URL).strip()
    return resolved or None


def _json_get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_put(url: str) -> Any:
    request = urllib.request.Request(url, data=b"", method="PUT")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _pick_ttbz_target(cdp_url: str) -> dict[str, Any]:
    pages = [target for target in _json_get(f"{cdp_url.rstrip('/')}/json/list") if target.get("type") == "page"]
    for page in pages:
        page_url = page.get("url") or ""
        if "ttbz.org.cn" in page_url:
            return page
    encoded = urllib.parse.quote(f"{TTBZ_ORIGIN}/standard.html", safe="")
    return _json_put(f"{cdp_url.rstrip('/')}/json/new?{encoded}")


async def _fetch_cookies_via_cdp(cdp_url: str) -> list[dict[str, Any]]:
    target = _pick_ttbz_target(cdp_url)
    websocket_url = target.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise TtbzBrowserSessionError("TTBZ Chrome 调试目标缺少 webSocketDebuggerUrl")

    next_id = 1

    async with websockets.connect(websocket_url, max_size=4_000_000) as ws:
        async def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            nonlocal next_id
            message_id = next_id
            next_id += 1
            payload: dict[str, Any] = {"id": message_id, "method": method}
            if params is not None:
                payload["params"] = params
            await ws.send(json.dumps(payload))
            while True:
                raw = await ws.recv()
                data = json.loads(raw)
                if data.get("id") != message_id:
                    continue
                if "error" in data:
                    raise TtbzBrowserSessionError(f"CDP {method} failed: {data['error']}")
                return data.get("result") or {}

        await call("Network.enable")
        result = await call("Network.getCookies", {"urls": [TTBZ_ORIGIN, f"{TTBZ_ORIGIN}/"]})
        cookies = result.get("cookies") or []
        if not cookies:
            result = await call("Network.getAllCookies")
            cookies = [
                item
                for item in (result.get("cookies") or [])
                if "ttbz.org.cn" in str(item.get("domain") or "")
            ]
        return cookies


def fetch_ttbz_browser_cookies(*, cdp_url: str | None = None) -> list[dict[str, Any]]:
    resolved = resolve_ttbz_cdp_url(cdp_url)
    if not resolved:
        return []
    return asyncio.run(_fetch_cookies_via_cdp(resolved))


def apply_ttbz_browser_cookies(client: httpx.Client, *, cdp_url: str | None = None) -> int:
    cookies = fetch_ttbz_browser_cookies(cdp_url=cdp_url)
    client.cookies.clear()
    for item in cookies:
        name = str(item.get("name") or "")
        value = str(item.get("value") or "")
        if not name:
            continue
        domain = str(item.get("domain") or ".ttbz.org.cn")
        if not domain.startswith("."):
            domain = f".{domain}"
        path = str(item.get("path") or "/")
        client.cookies.set(name, value, domain=domain, path=path)
    _sync_ttbz_login_marker_cookies(client)
    return len(cookies)


async def _fetch_access_token_via_cdp(cdp_url: str) -> str:
    target = _pick_ttbz_target(cdp_url)
    websocket_url = target.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise TtbzBrowserSessionError("TTBZ Chrome 调试目标缺少 webSocketDebuggerUrl")

    next_id = 1
    read_token_js = """
    (() => {
      let token = sessionStorage.getItem('token') || '';
      if (!token) {
        for (let i = 0; i < sessionStorage.length; i++) {
          const key = sessionStorage.key(i);
          if (key && key.endsWith('-accessToken')) {
            token = sessionStorage.getItem(key) || '';
            break;
          }
        }
      }
      return token || '';
    })()
    """

    async with websockets.connect(websocket_url, max_size=4_000_000) as ws:
        async def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            nonlocal next_id
            message_id = next_id
            next_id += 1
            payload: dict[str, Any] = {"id": message_id, "method": method}
            if params is not None:
                payload["params"] = params
            await ws.send(json.dumps(payload))
            while True:
                raw = await ws.recv()
                data = json.loads(raw)
                if data.get("id") != message_id:
                    continue
                if "error" in data:
                    raise TtbzBrowserSessionError(f"CDP {method} failed: {data['error']}")
                return data.get("result") or {}

        await call("Runtime.enable")
        page_url = str(target.get("url") or "")
        if "ttbz.org.cn" not in page_url or "login.html" in page_url:
            await call("Page.navigate", {"url": f"{TTBZ_ORIGIN}/standard.html"})
            await asyncio.sleep(2)
        result = await call("Runtime.evaluate", {"expression": read_token_js, "returnByValue": True})
        token = str((result.get("result") or {}).get("value") or "").strip()
        return token


def fetch_ttbz_browser_access_token(*, cdp_url: str | None = None) -> str:
    resolved = resolve_ttbz_cdp_url(cdp_url)
    if not resolved:
        return ""
    try:
        return asyncio.run(_fetch_access_token_via_cdp(resolved))
    except (OSError, TtbzBrowserSessionError):
        return ""


def apply_ttbz_browser_auth(client: httpx.Client, *, cdp_url: str | None = None) -> dict[str, Any]:
    cookie_count = apply_ttbz_browser_cookies(client, cdp_url=cdp_url)
    access_token = fetch_ttbz_browser_access_token(cdp_url=cdp_url)
    if access_token:
        client.headers["token"] = access_token
    elif "token" in client.headers:
        del client.headers["token"]
    return {"cookie_count": cookie_count, "has_access_token": bool(access_token)}


def probe_ttbz_bus_login(client: httpx.Client) -> dict[str, Any]:
    headers = {
        "User-Agent": str(client.headers.get("User-Agent") or "Mozilla/5.0"),
        "Referer": f"{TTBZ_ORIGIN}/standard.html",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json,*/*",
    }
    token = str(client.headers.get("token") or "").strip()
    if token:
        headers["token"] = token
    try:
        response = client.get(f"{TTBZ_BUS_API.rsplit('/', 1)[0]}/manager/info.do", headers=headers)
        if response.status_code == 401:
            return {"ok": False, "status": 401, "reason": "bus_unauthorized"}
        if response.status_code >= 400:
            return {"ok": False, "status": response.status_code, "reason": "bus_probe_failed"}
        payload = response.json()
        if isinstance(payload, dict) and payload.get("result"):
            return {"ok": True, "status": response.status_code, "reason": "bus_ok"}
        return {"ok": False, "status": response.status_code, "reason": str(payload.get("msg") or "bus_not_logged_in")}
    except httpx.HTTPError as exc:
        return {"ok": False, "status": None, "reason": f"bus_probe_error:{exc}"}


async def _download_clean_pdf_via_cdp(unique_id: str, *, cdp_url: str) -> tuple[bytes, str]:
    target = _pick_ttbz_target(cdp_url)
    websocket_url = target.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise TtbzBrowserSessionError("TTBZ Chrome 调试目标缺少 webSocketDebuggerUrl")

    detail_url = f"{TTBZ_ORIGIN}/standardDetail/{unique_id}.html"
    bus_url = f"{TTBZ_BUS_API}/getStdPdfWatermarked"
    js = f"""
    (async () => {{
      const uid = {json.dumps(unique_id)};
      const ref = {json.dumps(detail_url)};
      const bus = {json.dumps(bus_url)};
      let token = sessionStorage.getItem('token') || '';
      if (!token) {{
        for (let i = 0; i < sessionStorage.length; i++) {{
          const key = sessionStorage.key(i);
          if (key && key.endsWith('-accessToken')) {{
            token = sessionStorage.getItem(key) || '';
            break;
          }}
        }}
      }}
      const headers = {{
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json,*/*',
        'Referer': ref,
        'X-Requested-With': 'XMLHttpRequest',
      }};
      if (token) headers['token'] = token;
      const body = new URLSearchParams({{ operateType: '2', standardUniqueId: uid, fileLang: 'cn' }});
      const resp = await fetch(bus, {{ method: 'POST', headers, body, credentials: 'include' }});
      const ctype = resp.headers.get('content-type') || '';
      if (resp.status === 401) {{
        return {{ error: 'login_required', msg: '未检测到登录信息，请重新登录' }};
      }}
      if (ctype.includes('json')) {{
        const payload = await resp.json();
        if (!payload || !payload.result) {{
          return {{ error: 'api_failed', msg: payload && payload.msg ? payload.msg : '无正文 PDF' }};
        }}
        const data = payload.data;
        if (!data) return {{ error: 'missing_pdf_url' }};
        const pdfUrl = data.startsWith('http') ? data : (location.origin + data);
        const pdfResp = await fetch(pdfUrl, {{ credentials: 'include', headers: {{ Referer: ref, Accept: 'application/pdf,*/*' }} }});
        const buf = new Uint8Array(await pdfResp.arrayBuffer());
        let binary = '';
        const chunk = 0x8000;
        for (let i = 0; i < buf.length; i += chunk) {{
          binary += String.fromCharCode.apply(null, buf.subarray(i, i + chunk));
        }}
        return {{
          ok: true,
          pdfUrl,
          size: buf.length,
          isPdf: String.fromCharCode(buf[0], buf[1], buf[2], buf[3]) === '%PDF',
          pdfBase64: btoa(binary),
        }};
      }}
      const buf = new Uint8Array(await resp.arrayBuffer());
      let binary = '';
      const chunk = 0x8000;
      for (let i = 0; i < buf.length; i += chunk) {{
        binary += String.fromCharCode.apply(null, buf.subarray(i, i + chunk));
      }}
      return {{
        ok: true,
        pdfUrl: bus,
        size: buf.length,
        isPdf: String.fromCharCode(buf[0], buf[1], buf[2], buf[3]) === '%PDF',
        pdfBase64: btoa(binary),
      }};
    }})()
    """

    next_id = 1
    async with websockets.connect(websocket_url, max_size=32_000_000) as ws:
        async def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            nonlocal next_id
            message_id = next_id
            next_id += 1
            payload: dict[str, Any] = {"id": message_id, "method": method}
            if params is not None:
                payload["params"] = params
            await ws.send(json.dumps(payload))
            while True:
                raw = await ws.recv()
                data = json.loads(raw)
                if data.get("id") != message_id:
                    continue
                if "error" in data:
                    raise TtbzBrowserSessionError(f"CDP {method} failed: {data['error']}")
                return data.get("result") or {}

        await call("Page.enable")
        await call("Runtime.enable")
        await call("Page.navigate", {"url": detail_url})
        await asyncio.sleep(6)
        result = await call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
        value = (result.get("result") or {}).get("value") or {}
        if not isinstance(value, dict):
            raise TtbzBrowserSessionError("TTBZ CDP 下载返回非对象结果")
        if value.get("error") == "login_required":
            raise TtbzBrowserSessionError("TTBZ 登录态无效，请在 9223 Chrome 重新登录后再采集无水印正文")
        if value.get("error"):
            raise TtbzBrowserSessionError(str(value.get("msg") or value.get("error")))
        if not value.get("ok") or not value.get("isPdf"):
            raise TtbzBrowserSessionError("TTBZ 无水印 PDF 下载失败或响应非 PDF")
        pdf_bytes = base64.b64decode(str(value.get("pdfBase64") or ""))
        pdf_url = str(value.get("pdfUrl") or bus_url)
        return pdf_bytes, pdf_url


def download_ttbz_clean_pdf_via_cdp(unique_id: str, *, cdp_url: str | None = None) -> tuple[bytes, str]:
    resolved = resolve_ttbz_cdp_url(cdp_url)
    if not resolved:
        raise TtbzBrowserSessionError("TTBZ_CDP_URL 未配置")
    return asyncio.run(_download_clean_pdf_via_cdp(unique_id, cdp_url=resolved))


def _sync_ttbz_login_marker_cookies(client: httpx.Client) -> None:
    gov_session = ""
    for cookie in client.cookies.jar:
        if cookie.name == "GOV_SHIRO_SESSION_ID" and cookie.value:
            gov_session = cookie.value
            break
    if not gov_session:
        return
    client.cookies.set("IS_LOGGED_IN", "1", domain=".ttbz.org.cn", path="/")
    client.cookies.set("MANAGER_SESSION_ID", gov_session, domain=".ttbz.org.cn", path="/")


def check_ttbz_browser_login(*, cdp_url: str | None = None, client: httpx.Client | None = None) -> dict[str, Any]:
    resolved = resolve_ttbz_cdp_url(cdp_url)
    proxy = resolve_ttbz_http_proxy()
    if not resolved:
        return {"enabled": False, "cdp_url": None, "reachable": False, "cookie_count": 0, "logged_in_hint": None}

    try:
        version = _json_get(f"{resolved.rstrip('/')}/json/version")
    except OSError as exc:
        return {
            "enabled": True,
            "cdp_url": resolved,
            "proxy": proxy,
            "reachable": False,
            "cookie_count": 0,
            "logged_in_hint": str(exc),
        }

    owns_client = client is None
    if client is None:
        kwargs: dict = {"follow_redirects": True, "timeout": 20, "headers": {"User-Agent": "Mozilla/5.0"}}
        if proxy:
            kwargs["proxy"] = proxy
        client = httpx.Client(**kwargs)
    try:
        auth = apply_ttbz_browser_auth(client, cdp_url=resolved)
        cookie_count = int(auth.get("cookie_count") or 0)
        has_access_token = bool(auth.get("has_access_token"))
        logged_in_hint = "unknown"
        site_status: int | None = None
        bus_probe: dict[str, Any] = {}
        try:
            response = client.get(f"{TTBZ_ORIGIN}/standard.html", headers={"Referer": f"{TTBZ_ORIGIN}/"})
            site_status = response.status_code
            text = response.text or ""
            if site_status == 403:
                logged_in_hint = "blocked_403_need_proxy"
            elif any(token in text for token in ("退出", "个人中心", "我的标准", "logout")):
                logged_in_hint = "likely_logged_in"
            elif any(token in text for token in ("登录", "注册", "login")):
                logged_in_hint = "likely_logged_out"
        except httpx.HTTPError as exc:
            logged_in_hint = f"probe_failed:{exc}"
        if logged_in_hint != "blocked_403_need_proxy":
            bus_probe = probe_ttbz_bus_login(client)
            if bus_probe.get("ok"):
                logged_in_hint = "bus_logged_in"
            elif has_access_token and logged_in_hint == "likely_logged_in":
                logged_in_hint = "likely_logged_in_bus_rejected"
            elif not has_access_token and logged_in_hint == "likely_logged_in":
                logged_in_hint = "likely_logged_out_missing_token"
        return {
            "enabled": True,
            "cdp_url": resolved,
            "proxy": proxy,
            "reachable": True,
            "browser": version.get("Browser"),
            "cookie_count": cookie_count,
            "has_access_token": has_access_token,
            "site_status": site_status,
            "bus_probe": bus_probe,
            "logged_in_hint": logged_in_hint,
        }
    finally:
        if owns_client and client is not None:
            client.close()
