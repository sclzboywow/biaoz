from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import websockets

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.download_service import DownloadedContent, archive_downloaded_content  # noqa: E402
from app.settings_store import ensure_default_settings  # noqa: E402
from app.storage import configured_storage_root  # noqa: E402


SPC_BASE_URL = "https://www.spc.org.cn"
ONLINE_READING_RE = re.compile(r"/stdlib/onlinereading\?token=", re.I)
RATE_LIMIT_TOKENS = ("请求过多", "访问过于频繁", "Too Many Requests", "429")
ONLINE_UNAVAILABLE_TOKENS = (
    "\u798f\u6615\u9605\u8bfb\u5668\u7f51\u9875\u7248",
    "\u683c\u5f0f\u9519\u8bef",
    "\u4e0d\u662f\u4e00\u4e2aPDF\u6587\u4ef6",
    "\u6587\u4ef6\u5df2\u635f\u574f",
    "\u7248\u6743\u9650\u5236",
    "\u6682\u4e0d\u63d0\u4f9b\u5728\u7ebf\u9605\u8bfb\u670d\u52a1",
    "\u4e0d\u63d0\u4f9b\u5728\u7ebf\u9605\u8bfb",
    "\u6807\u51c6\u8d2d\u4e70",
)
ONLINE_UNAVAILABLE_CHECK_EXPRESSION = r"""(() => {
  const text = document.body ? document.body.innerText : '';
  const hasError = /\u798f\u6615\u9605\u8bfb\u5668\u7f51\u9875\u7248|\u683c\u5f0f\u9519\u8bef|\u4e0d\u662f\u4e00\u4e2aPDF\u6587\u4ef6|\u6587\u4ef6\u5df2\u635f\u574f|\u7248\u6743\u9650\u5236|\u6682\u4e0d\u63d0\u4f9b\u5728\u7ebf\u9605\u8bfb\u670d\u52a1|\u4e0d\u63d0\u4f9b\u5728\u7ebf\u9605\u8bfb|\u6807\u51c6\u8d2d\u4e70/.test(text);
  let clicked = false;
  if (/\u798f\u6615\u9605\u8bfb\u5668\u7f51\u9875\u7248|\u683c\u5f0f\u9519\u8bef|\u4e0d\u662f\u4e00\u4e2aPDF\u6587\u4ef6|\u6587\u4ef6\u5df2\u635f\u574f/.test(text)) {
    const okRe = /\u786e\u5b9a|OK|\u5173\u95ed|Close/;
    const candidates = Array.from(document.querySelectorAll('button,a,input,[role="button"],.layui-layer-btn0,.layui-layer-close'));
    const button = candidates.find((el) => okRe.test(((el.innerText || el.value || el.getAttribute('aria-label') || el.title || '') + '').trim()));
    if (button) {
      button.click();
      clicked = true;
    }
  }
  return {online_unavailable: hasError, clicked, text: hasError ? text.slice(0, 500) : ''};
})()"""


class SpcRateLimitError(RuntimeError):
    pass


class SpcOnlineUnavailableError(RuntimeError):
    pass


def _json_get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_put(url: str) -> Any:
    request = urllib.request.Request(url, data=b"", method="PUT")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _find_target(cdp_url: str, detail_url: str | None) -> dict[str, Any] | None:
    targets = _json_get(f"{cdp_url.rstrip('/')}/json/list")
    pages = [target for target in targets if target.get("type") == "page"]
    if detail_url:
        for target in pages:
            if target.get("url") == detail_url:
                return target
        for target in pages:
            if detail_url.rsplit("/", 1)[-1] in target.get("url", ""):
                return target
    for target in pages:
        if target.get("url", "").startswith(SPC_BASE_URL):
            return target
    return pages[0] if pages else None


def _open_target(cdp_url: str, url: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(url, safe="")
    return _json_put(f"{cdp_url.rstrip('/')}/json/new?{encoded}")


def _content_disposition_file_name(standard_no: str) -> str:
    safe = _safe_pdf_file_stem(standard_no)
    return f'form-data; name="attachment"; filename="{safe}.pdf"'


def _safe_pdf_file_stem(value: str) -> str:
    return re.sub(r'[<>:"/\\\\|?*]+', "-", value).strip(" .-") or "spc-online-reading"


def _safe_content_disposition(content_disposition: str | None, standard_no: str) -> str:
    if not content_disposition:
        return _content_disposition_file_name(standard_no)
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition, flags=re.I)
    if not match:
        return content_disposition
    raw_name = urllib.parse.unquote(match.group(1))
    raw_stem = raw_name[:-4] if raw_name.lower().endswith(".pdf") else raw_name
    safe_name = _safe_pdf_file_stem(raw_stem or standard_no) + ".pdf"
    return f'form-data; name="attachment"; filename="{safe_name}"'


async def _capture_pdf_from_page(
    websocket_url: str,
    standard_no: str,
    standclass: str,
    detail_url: str,
    timeout_seconds: int,
) -> DownloadedContent:
    next_id = 1
    pending: dict[int, asyncio.Future] = {}
    online_url: str | None = None
    online_status: int | None = None
    online_content_type: str | None = None
    online_content_disposition: str | None = None

    async with websockets.connect(websocket_url, max_size=100_000_000) as ws:
        async def send_later(method: str, params: dict[str, Any] | None = None) -> None:
            nonlocal next_id
            msg = {"id": next_id, "method": method}
            if params is not None:
                msg["params"] = params
            pending[next_id] = asyncio.get_event_loop().create_future()
            command_id = next_id
            next_id += 1
            await ws.send(json.dumps(msg))
            return command_id

        await send_later("Network.enable")
        await send_later(
            "Fetch.enable",
            {
                "patterns": [
                    {
                        "urlPattern": "*://www.spc.org.cn/stdlib/onlinereading*",
                        "requestStage": "Response",
                    }
                ]
            },
        )
        await send_later("Page.enable")
        await send_later("Runtime.enable")
        await send_later("Page.navigate", {"url": detail_url})

        submitted = False
        online_loaded = False
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1)
            except asyncio.TimeoutError:
                if not submitted:
                    await send_later(
                        "Runtime.evaluate",
                        {"expression": ONLINE_UNAVAILABLE_CHECK_EXPRESSION, "returnByValue": True},
                    )
                    expr = f"""(() => {{
                      const form = document.querySelector('#stdonline');
                      if (!form) return {{submitted:false, reason:'no #stdonline', readyState:document.readyState, url:location.href, text:document.body ? document.body.innerText.slice(0,500) : ''}};
                      const a100 = form.querySelector('input[name=a100]');
                      const standclass = form.querySelector('input[name=standclass]');
                      if (a100) a100.value = {json.dumps(standard_no)};
                      if (standclass) standclass.value = {json.dumps(standclass)};
                      form.target = '_self';
                      form.method = 'post';
                      form.action = '/stdlib/stdonline';
                      form.submit();
                      return {{submitted:true, url:location.href, a100:a100 && a100.value, standclass:standclass && standclass.value}};
                    }})()"""
                    await send_later("Runtime.evaluate", {"expression": expr, "returnByValue": True})
                else:
                    await send_later(
                        "Runtime.evaluate",
                        {"expression": ONLINE_UNAVAILABLE_CHECK_EXPRESSION, "returnByValue": True},
                    )
                continue

            event = json.loads(raw)
            if "id" in event and event["id"] in pending:
                future = pending.pop(event["id"])
                if not future.done():
                    future.set_result(event)
                result_value = event.get("result", {}).get("result", {}).get("value")
                if isinstance(result_value, dict):
                    if result_value.get("online_unavailable"):
                        snippet = str(result_value.get("text") or "")
                        raise SpcOnlineUnavailableError(f"SPC online reading unavailable: {snippet[:200]!r}")
                    if result_value.get("submitted"):
                        submitted = True
                    elif result_value.get("reason") == "no #stdonline" and result_value.get("readyState") == "complete":
                        raise SpcOnlineUnavailableError("SPC detail page has no online reading form")
                continue

            method = event.get("method")
            params = event.get("params") or {}
            if method == "Fetch.requestPaused":
                request = params.get("request") or {}
                url = request.get("url", "")
                if not ONLINE_READING_RE.search(url):
                    await send_later("Fetch.continueRequest", {"requestId": params.get("requestId")})
                    continue
                headers_list = params.get("responseHeaders") or []
                headers = {item.get("name", ""): item.get("value", "") for item in headers_list}
                online_url = url
                online_status = int(params.get("responseStatusCode") or 200)
                online_content_type = headers.get("Content-Type") or headers.get("content-type") or "application/pdf"
                online_content_disposition = headers.get("Content-Disposition") or headers.get("content-disposition")
                body_command_id = await send_later("Fetch.getResponseBody", {"requestId": params.get("requestId")})
                while time.time() < deadline:
                    body_raw = await asyncio.wait_for(ws.recv(), timeout=max(1, int(deadline - time.time())))
                    body_event = json.loads(body_raw)
                    if body_event.get("id") != body_command_id:
                        continue
                    pending.pop(body_event["id"], None)
                    value = body_event.get("result") or {}
                    break
                else:
                    raise RuntimeError("Timed out fetching SPC online PDF bytes from intercepted response")
                raw_body = value.get("body") or ""
                content = base64.b64decode(raw_body) if value.get("base64Encoded") else raw_body.encode("latin1")
                if not content.startswith(b"%PDF"):
                    snippet = content[:1000].decode("utf-8", errors="ignore")
                    if any(token in snippet for token in RATE_LIMIT_TOKENS):
                        raise SpcRateLimitError(f"SPC online reading rate limited: {snippet[:200]!r}")
                    if any(token in snippet for token in ONLINE_UNAVAILABLE_TOKENS):
                        raise SpcOnlineUnavailableError(f"SPC online reading unavailable: {snippet[:200]!r}")
                    raise RuntimeError(f"SPC online reading response is not a PDF: first_bytes={content[:20]!r}")
                await send_later(
                    "Fetch.fulfillRequest",
                    {
                        "requestId": params.get("requestId"),
                        "responseCode": online_status,
                        "responseHeaders": headers_list,
                        "body": base64.b64encode(content).decode("ascii"),
                    },
                )
                return DownloadedContent(
                    status_code=online_status or 200,
                    url=online_url or f"{SPC_BASE_URL}/stdlib/onlinereading",
                    content=content,
                    content_type=online_content_type or "application/pdf",
                    content_disposition=_safe_content_disposition(
                        online_content_disposition,
                        standard_no,
                    ),
                )

    raise RuntimeError("Timed out waiting for SPC online reading PDF response")


def _upsert_url_source(db, detail_url: str, standard_no: str, title: str | None) -> models.UrlSource:
    url = f"spc-online-reading://{standard_no}"
    source = db.query(models.UrlSource).filter(models.UrlSource.url == url).first()
    if source is None:
        source = models.UrlSource(url=url)
        db.add(source)
        db.flush()
    source.source_name = title or standard_no
    source.source_unit = "中国标准在线服务网"
    source.source_type = "SPC会员在线阅读PDF流"
    source.category = "SPC在线阅读授权文件"
    source.check_frequency = "manual"
    source.remark = f"standard_no={standard_no}；detail_url={detail_url}；采集方式=会员在线阅读官方PDF流"
    return source


def ingest_one_spc_online_file(
    *,
    standard_no: str,
    detail_url: str,
    standclass: str = "CN",
    title: str | None = None,
    cdp_url: str = "http://127.0.0.1:9222",
    timeout_seconds: int = 240,
):
    target = _find_target(cdp_url, detail_url)
    if target is None:
        target = _open_target(cdp_url, detail_url)
    websocket_url = target.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise SystemExit("Chrome target has no websocket debugger URL")

    downloaded = asyncio.run(
        _capture_pdf_from_page(
            websocket_url=websocket_url,
            standard_no=standard_no,
            standclass=standclass,
            detail_url=detail_url,
            timeout_seconds=timeout_seconds,
        )
    )

    settings = get_settings()
    with SessionLocal() as db:
        ensure_default_settings(db)
        source = _upsert_url_source(db, detail_url, standard_no, title)
        storage_root = configured_storage_root(db, settings.storage_root)
        result = archive_downloaded_content(db, source, storage_root, downloaded)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest one authorized SPC online-reading PDF into the local file library.")
    parser.add_argument("--standard-no", required=True)
    parser.add_argument("--detail-url", required=True)
    parser.add_argument("--standclass", default="CN")
    parser.add_argument("--title")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    result = ingest_one_spc_online_file(
        standard_no=args.standard_no,
        detail_url=args.detail_url,
        standclass=args.standclass,
        title=args.title,
        cdp_url=args.cdp_url,
        timeout_seconds=args.timeout,
    )

    print("spc_file_ingest_result " + json.dumps(result.model_dump(), ensure_ascii=False, default=str))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
