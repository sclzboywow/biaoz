"""Download MOT jtst.mot.gov.cn kfs standard PDFs with captcha OCR."""

from __future__ import annotations

import re
import time
from urllib.parse import urlparse

import httpx

from app.download_service import DownloadedContent
from app.gb688_captcha_download import (
    OpenstdCaptchaError,
    OpenstdCaptchaIncorrectError,
    OpenstdDownloadUnavailableError,
    solve_captcha_image,
)

MOT_BASE = "https://jtst.mot.gov.cn"
MOT_KFS_DOWNLOAD_PREFIX = f"{MOT_BASE}/kfs/file/downloadStd/"
LOCATION_S_RE = re.compile(r"/kfs/file/downloadStd/([0-9a-f]+)", re.I)


class MotKfsCaptchaError(OpenstdCaptchaError):
    pass


class MotKfsCaptchaIncorrectError(OpenstdCaptchaIncorrectError):
    pass


class MotKfsDownloadUnavailableError(OpenstdDownloadUnavailableError):
    pass


def extract_mot_kfs_location_s(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        match = LOCATION_S_RE.search(value)
        if match:
            return match.group(1)
    return None


def mot_kfs_download_page_url(location_s: str) -> str:
    return f"{MOT_KFS_DOWNLOAD_PREFIX}{location_s}"


def _default_headers(*, referer: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _detail_pid(detail_url: str | None) -> str | None:
    if not detail_url:
        return None
    from urllib.parse import parse_qs

    query = parse_qs(urlparse(detail_url).query)
    pid = (query.get("id") or [None])[0]
    return str(pid) if pid else None


def _warm_mot_session(http: httpx.Client, *, pid: str | None, detail_url: str | None) -> str:
    referer = detail_url or MOT_BASE
    if pid:
        view_url = f"{MOT_BASE}/hb/search/stdHBView?id={pid}"
        http.get(view_url, headers={"Referer": referer, "Accept": "text/html,*/*"})
        return view_url
    return referer


def _looks_like_captcha_html(content: bytes) -> bool:
    text = content[:8000].decode("utf-8", errors="ignore")
    return any(token in text for token in ("验证码", "标准下载", "不正确", "看不清"))


def download_mot_kfs_pdf(
    location_s: str,
    *,
    pid: str | None = None,
    detail_url: str | None = None,
    timeout_seconds: int = 120,
    max_attempts: int = 5,
    client: httpx.Client | None = None,
) -> DownloadedContent:
    location_s = (location_s or "").strip()
    if not location_s:
        raise MotKfsDownloadUnavailableError("缺少 MOT kfs location_s")

    if pid is None and detail_url:
        pid = _detail_pid(detail_url)

    download_page_url = mot_kfs_download_page_url(location_s)
    captcha_url = f"{MOT_BASE}/kfs/file/validate-code"
    owns_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout_seconds, headers=_default_headers())
    last_error: Exception | None = None

    try:
        referer = _warm_mot_session(http, pid=pid, detail_url=detail_url)
        page = http.get(download_page_url, headers={"Referer": referer, "Accept": "text/html,*/*"})
        page.raise_for_status()

        for attempt in range(1, max(max_attempts, 1) + 1):
            try:
                captcha = http.get(
                    captcha_url,
                    headers={
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        "Referer": download_page_url,
                    },
                )
                captcha.raise_for_status()
                if not captcha.content.startswith(b"\x89PNG") and not captcha.content.startswith(b"\xff\xd8"):
                    content_type = captcha.headers.get("content-type") or ""
                    if not content_type.lower().startswith("image/"):
                        raise MotKfsCaptchaError(f"MOT 验证码接口返回异常：{content_type}")

                verify_code = solve_captcha_image(captcha.content)
                response = http.post(
                    download_page_url,
                    data={"validateCode": verify_code},
                    headers={
                        "Referer": download_page_url,
                        "Accept": "application/pdf,*/*",
                    },
                )
                response.raise_for_status()
                if not response.content.startswith(b"%PDF"):
                    if _looks_like_captcha_html(response.content):
                        raise MotKfsCaptchaIncorrectError(f"MOT 验证码不正确：{verify_code!r}")
                    snippet = response.content[:200].decode("utf-8", errors="ignore")
                    raise MotKfsDownloadUnavailableError(f"MOT 未返回 PDF：{snippet[:120]!r}")

                return DownloadedContent(
                    status_code=response.status_code,
                    url=str(response.url),
                    content=response.content,
                    content_type=response.headers.get("content-type") or "application/pdf",
                    content_disposition=response.headers.get("content-disposition"),
                )
            except MotKfsCaptchaIncorrectError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise
                time.sleep(min(attempt, 3))
            except MotKfsCaptchaError:
                raise
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise MotKfsCaptchaError(f"MOT kfs 下载失败：{exc}") from exc
                time.sleep(min(attempt, 3))
    finally:
        if owns_client:
            http.close()

    raise MotKfsCaptchaError(f"MOT kfs 下载失败：{last_error}") from last_error


def download_mot_kfs_pdf_from_url(
    url: str,
    *,
    detail_url: str | None = None,
    timeout_seconds: int = 120,
    max_attempts: int = 5,
    client: httpx.Client | None = None,
) -> DownloadedContent:
    location_s = extract_mot_kfs_location_s(url)
    if not location_s:
        raise MotKfsDownloadUnavailableError("无法从 URL 解析 MOT kfs location_s")
    pid = _detail_pid(detail_url)
    return download_mot_kfs_pdf(
        location_s,
        pid=pid,
        detail_url=detail_url,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        client=client,
    )
