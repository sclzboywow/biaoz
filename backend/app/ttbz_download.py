from __future__ import annotations

import json
import re

import httpx

from app.download_service import DownloadedContent, archive_content_disposition, safe_archive_file_stem
from app.standard_number import normalize_standard_no
from app.ttbz_browser_session import (
    TtbzBrowserSessionError,
    apply_ttbz_browser_auth,
    download_ttbz_clean_pdf_via_cdp,
    resolve_ttbz_cdp_url,
)

TTBZ_API = "https://www.ttbz.org.cn/cms-proxy/ms/portal/standardInfo"
TTBZ_BUS_API = "https://www.ttbz.org.cn/cms-proxy/ms/bus/standardInfo"
TTBZ_ORIGIN = "https://www.ttbz.org.cn"
DETAIL_PAGE_RE = re.compile(r"standardDetail/([^.]+)\.html", re.I)
ANNOUNCEMENT_FILE_TYPE = 2
BODY_FILE_TYPE = 1


class TtbzDownloadError(RuntimeError):
    pass


class TtbzDownloadUnavailableError(TtbzDownloadError):
    pass


def _headers(*, referer: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer or f"{TTBZ_ORIGIN}/standard.html",
    }


def _bus_headers(http: httpx.Client, *, referer: str) -> dict[str, str]:
    headers = {
        **_headers(referer=referer),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json,*/*",
    }
    token = str(http.headers.get("token") or "").strip()
    if token:
        headers["token"] = token
    return headers


def extract_ttbz_unique_id(*values: str | None, source_book_id: str | None = None) -> str | None:
    for value in values:
        if not value:
            continue
        match = DETAIL_PAGE_RE.search(value)
        if match:
            return match.group(1)
    if source_book_id and re.fullmatch(r"[A-Za-z0-9]{16,128}", source_book_id):
        return source_book_id
    return None


def canonical_ttbz_url(unique_id: str) -> str:
    return f"{TTBZ_ORIGIN}/standardDetail/{unique_id}.html"


def build_ttbz_archive_file_stem(*, standard_no: str | None, standard_name: str | None) -> str:
    number = ""
    if standard_no:
        parts = normalize_standard_no(standard_no)
        number = safe_archive_file_stem((parts.normalized or standard_no).replace("/", "-"), fallback="")
    title = safe_archive_file_stem(standard_name or "", fallback="")
    if number and title:
        if title.startswith(number) or number in title:
            return title
        return f"{number} {title}"
    return number or title or "ttbz-standard"


def _parse_json(response: httpx.Response) -> dict:
    if response.status_code == 403:
        raise TtbzDownloadError("ttbz API blocked (403)")
    if response.status_code == 429:
        raise TtbzDownloadError("ttbz API rate limited (429)")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TtbzDownloadError("ttbz API returned non-object JSON")
    return payload


def _detail_open_blocked(detail: dict) -> bool:
    open_flag = str(detail.get("isOpen") or detail.get("openFlag") or "").strip()
    open_name = str(detail.get("isOpenName") or detail.get("openStatusName") or "").strip()
    return open_flag in {"0", "false", "False"} or open_name in {"否", "不公开", "未公开"}


def fetch_portal_standard_detail(
    unique_id: str,
    *,
    detail_url: str | None = None,
    client: httpx.Client,
) -> dict:
    referer = detail_url or canonical_ttbz_url(unique_id)
    response = client.post(
        f"{TTBZ_API}/getPortalStandardById",
        data={"standardUniqueId": unique_id},
        headers=_headers(referer=referer),
    )
    if response.status_code == 403:
        raise TtbzDownloadError("ttbz portal API blocked (403)")
    if response.status_code == 405:
        raise TtbzDownloadError("ttbz portal API blocked (405)")
    payload = _parse_json(response)
    detail = payload.get("data")
    if not isinstance(detail, dict):
        raise TtbzDownloadUnavailableError("portal detail missing")
    return detail


def _is_announcement_file(item: dict) -> bool:
    file_type = item.get("fileType")
    if file_type == ANNOUNCEMENT_FILE_TYPE:
        return True
    label = str(item.get("fileTypeName") or "")
    original = str(item.get("originalFileName") or "")
    return "公告" in label or "公告" in original


def _is_body_file(item: dict) -> bool:
    if _is_announcement_file(item):
        return False
    file_type = item.get("fileType")
    label = str(item.get("fileTypeName") or "")
    original = str(item.get("originalFileName") or "")
    if file_type == BODY_FILE_TYPE:
        return True
    for keyword in ("正文", "标准文本", "标准全文", "全文", "团体标准"):
        if keyword in label or keyword in original:
            return True
    file_url = str(item.get("fileUrl") or "").strip()
    file_format = str(item.get("fileFormat") or "").lower()
    return bool(file_url) and (file_format == "pdf" or file_url.lower().endswith(".pdf"))


def resolve_portal_body_pdf_path(detail: dict) -> str | None:
    files = [item for item in (detail.get("files") or []) if isinstance(item, dict)]
    body_files = [item for item in files if _is_body_file(item)]
    if body_files:
        return str(body_files[0].get("fileUrl") or "").strip() or None
    return None


def _only_announcement_files(detail: dict) -> bool:
    files = [item for item in (detail.get("files") or []) if isinstance(item, dict)]
    if not files:
        return False
    return all(_is_announcement_file(item) for item in files)


def _absolute_ttbz_url(path_or_url: str) -> str:
    value = path_or_url.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if not value.startswith("/"):
        value = f"/{value}"
    return f"{TTBZ_ORIGIN}{value}"


def _download_pdf_response(
    http: httpx.Client,
    pdf_url: str,
    *,
    referer: str,
) -> httpx.Response:
    response = http.get(
        pdf_url,
        headers={
            **_headers(referer=referer),
            "Accept": "application/pdf,*/*",
        },
    )
    if response.status_code == 403:
        raise TtbzDownloadError("ttbz pdf download blocked (403)")
    response.raise_for_status()
    return response


def _try_download_clean_bus_pdf(
    http: httpx.Client,
    unique_id: str,
    *,
    referer: str,
) -> tuple[bytes, str] | None:
    response = http.post(
        f"{TTBZ_BUS_API}/getStdPdfWatermarked",
        data={"operateType": "2", "standardUniqueId": unique_id, "fileLang": "cn"},
        headers=_bus_headers(http, referer=referer),
    )
    if response.status_code in {403, 405, 429}:
        raise TtbzDownloadError(f"ttbz clean PDF API blocked ({response.status_code})")
    if response.status_code == 401:
        return None
    if response.status_code >= 400:
        return None
    if response.content.startswith(b"%PDF"):
        return response.content, f"{TTBZ_BUS_API}/getStdPdfWatermarked"

    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if not payload.get("result"):
        msg = str(payload.get("msg") or "").strip()
        if "登录" in msg:
            return None
        if msg:
            raise TtbzDownloadUnavailableError(f"平台暂无标准正文 PDF：{msg}")
        return None

    data = payload.get("data")
    if not isinstance(data, str) or not data.strip():
        return None
    pdf_url = _absolute_ttbz_url(data)
    pdf_bytes = _download_pdf_response(http, pdf_url, referer=referer).content
    return pdf_bytes, pdf_url


def _try_download_standard_api(
    http: httpx.Client,
    unique_id: str,
    *,
    referer: str,
) -> bytes | None:
    response = http.post(
        f"{TTBZ_API}/downLoadStandard",
        data={"standardUniqueId": unique_id},
        headers={
            **_headers(referer=referer),
            "Accept": "application/pdf,*/*",
        },
    )
    if response.status_code in {403, 405, 429}:
        raise TtbzDownloadError(f"ttbz download API blocked ({response.status_code})")
    if response.status_code >= 400:
        return None
    if response.content.startswith(b"%PDF"):
        return response.content
    return None


def _try_download_clean_bus_pdf_via_cdp(unique_id: str) -> tuple[bytes, str] | None:
    if not resolve_ttbz_cdp_url():
        return None
    try:
        return download_ttbz_clean_pdf_via_cdp(unique_id)
    except TtbzBrowserSessionError as exc:
        message = str(exc)
        if "登录" in message:
            raise TtbzDownloadUnavailableError(message) from exc
        return None


def download_ttbz_pdf(
    unique_id: str,
    *,
    detail_url: str | None = None,
    standard_no: str | None = None,
    standard_name: str | None = None,
    timeout_seconds: int = 60,
    client: httpx.Client | None = None,
) -> DownloadedContent:
    owns_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout_seconds, headers=_headers())
    if owns_client and resolve_ttbz_cdp_url():
        apply_ttbz_browser_auth(http)
    referer = detail_url or canonical_ttbz_url(unique_id)
    file_stem = build_ttbz_archive_file_stem(standard_no=standard_no, standard_name=standard_name)
    content_disposition = archive_content_disposition(file_stem)
    try:
        detail = fetch_portal_standard_detail(unique_id, detail_url=detail_url, client=http)
        if _detail_open_blocked(detail):
            raise TtbzDownloadUnavailableError("团体标准未公开，无法下载")

        pdf_bytes: bytes | None = None
        source_url = referer

        standard_pdf_url = str(detail.get("standardPdfUrl") or "").strip()
        if standard_pdf_url:
            source_url = _absolute_ttbz_url(standard_pdf_url)
            pdf_bytes = _download_pdf_response(http, source_url, referer=referer).content
        else:
            clean = _try_download_clean_bus_pdf(http, unique_id, referer=referer)
            if not clean:
                clean = _try_download_clean_bus_pdf_via_cdp(unique_id)
            if clean:
                pdf_bytes, source_url = clean
            elif str(detail.get("hasCnPdf") or "").strip().lower() in {"true", "1", "yes"}:
                raise TtbzDownloadUnavailableError(
                    "TTBZ 无水印正文下载失败，请在 9223 Chrome 重新登录会员账号后再采集"
                )
            else:
                pdf_bytes = _try_download_standard_api(http, unique_id, referer=referer)
                if pdf_bytes:
                    source_url = f"{TTBZ_API}/downLoadStandard"
                else:
                    body_path = resolve_portal_body_pdf_path(detail)
                    if body_path:
                        source_url = _absolute_ttbz_url(body_path)
                        pdf_bytes = _download_pdf_response(http, source_url, referer=referer).content
                    elif _only_announcement_files(detail):
                        raise TtbzDownloadUnavailableError("平台暂无标准正文 PDF（当前仅有公告文件）")
                    else:
                        raise TtbzDownloadUnavailableError("无 PDF 文件（hasCnPdf=false 或 files 为空）")

        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            raise TtbzDownloadUnavailableError("无标准正文 PDF 或响应非 PDF")

        return DownloadedContent(
            status_code=200,
            url=source_url,
            content=pdf_bytes,
            content_type="application/pdf",
            content_disposition=content_disposition,
        )
    finally:
        if owns_client:
            http.close()
