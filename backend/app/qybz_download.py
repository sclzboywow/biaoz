from __future__ import annotations

import re

import httpx

from app.download_service import DownloadedContent

QYBZ_FILE_DOWN_URL = "https://www.qybz.org.cn/usercenter/detail.fileDown"
STANDARD_ID_RE = re.compile(r'name="standardId"\s+value="([^"]+)"', re.I)


class QybzDownloadError(RuntimeError):
    pass


class QybzDownloadUnavailableError(QybzDownloadError):
    pass


def _headers(*, referer: str) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer,
    }


def extract_qybz_standard_id(*values: str | None, source_book_id: str | None = None) -> str | None:
    for value in values:
        if not value:
            continue
        match = STANDARD_ID_RE.search(value)
        if match:
            return match.group(1)
    if source_book_id and re.fullmatch(r"[A-Za-z0-9]{16,128}", source_book_id):
        return source_book_id
    return None


def download_qybz_pdf(
    detail_url: str,
    *,
    standard_id: str | None = None,
    timeout_seconds: int = 60,
    client: httpx.Client | None = None,
) -> DownloadedContent:
    owns_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout_seconds)
    try:
        page = http.get(detail_url, headers=_headers(referer="https://www.qybz.org.cn/"))
        page.raise_for_status()
        resolved_id = standard_id or extract_qybz_standard_id(page.text, source_book_id=None)
        if not resolved_id:
            raise QybzDownloadUnavailableError("详情页未找到 standardId")

        response = http.post(
            QYBZ_FILE_DOWN_URL,
            data={"standardId": resolved_id},
            headers=_headers(referer=detail_url),
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type") or ""
        if response.content.startswith(b"%PDF"):
            return DownloadedContent(
                status_code=response.status_code,
                url=str(response.url),
                content=response.content,
                content_type=content_type or "application/pdf",
                content_disposition=response.headers.get("content-disposition"),
            )
        if "geetest" in response.text.lower() or "window.open" in response.text:
            raise QybzDownloadUnavailableError("企业标准下载需极验验证，暂无法自动采集")
        raise QybzDownloadUnavailableError(f"非 PDF 响应：{content_type or response.text[:120]}")
    finally:
        if owns_client:
            http.close()
