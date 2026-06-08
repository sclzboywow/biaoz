from __future__ import annotations

import re
import time

import httpx

from app.download_service import DownloadedContent
from app.gb688_captcha_download import solve_captcha_image

PORTAL_PK_RE = re.compile(
    r"https://(?:hbba|dbba)\.sacinfo\.org\.cn/(?:portal/online|stdDetail)/([A-Za-z0-9]+)",
    re.I,
)
PORTAL_BASE_RE = re.compile(
    r"https://(hbba|dbba)\.sacinfo\.org\.cn/(?:portal/online|stdDetail)/([A-Za-z0-9]+)",
    re.I,
)


class SamrPortalCaptchaError(RuntimeError):
    pass


class SamrPortalCaptchaIncorrectError(SamrPortalCaptchaError):
    pass


class SamrPortalDownloadUnavailableError(SamrPortalCaptchaError):
    pass


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def extract_portal_pk(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        match = PORTAL_PK_RE.search(value)
        if match:
            return match.group(1)
    return None


def extract_portal_base_url(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        match = PORTAL_BASE_RE.search(value)
        if match:
            return f"https://{match.group(1).lower()}.sacinfo.org.cn"
    return None


def portal_online_url(base_url: str, pk: str) -> str:
    return f"{base_url.rstrip('/')}/portal/online/{pk}"


def portal_detail_url(base_url: str, pk: str) -> str:
    return f"{base_url.rstrip('/')}/stdDetail/{pk}"


def extract_portal_info(*values: str | None, source_book_id: str | None = None) -> tuple[str, str] | None:
    base_url = extract_portal_base_url(*values)
    pk = extract_portal_pk(*values)
    if not pk and source_book_id and re.fullmatch(r"[A-Za-z0-9]{32,128}", source_book_id):
        pk = source_book_id
    if not base_url or not pk:
        return None
    return base_url, pk


def download_sacinfo_portal_pdf(
    base_url: str,
    pk: str,
    *,
    referer: str | None = None,
    timeout_seconds: int = 60,
    max_attempts: int = 3,
    client: httpx.Client | None = None,
) -> DownloadedContent:
    base_url = base_url.rstrip("/")
    pk = (pk or "").strip()
    if not base_url or not pk:
        raise SamrPortalDownloadUnavailableError("缺少 sacinfo portal 下载参数")

    online_url = portal_online_url(base_url, pk)
    page_referer = referer or portal_detail_url(base_url, pk)
    owns_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout_seconds, headers=_default_headers())
    last_error: Exception | None = None

    try:
        page = http.get(online_url, headers={"Accept": "text/html,*/*", "Referer": page_referer})
        page.raise_for_status()
        if "/portal/validate-code" not in page.text:
            reason_match = re.search(r"<p>(.*?)</p>", page.text, flags=re.S)
            reason = re.sub(r"\s+", " ", reason_match.group(1)).strip() if reason_match else ""
            detail = f"该来源当前未提供验证码下载入口{f'：{reason}' if reason else ''}"
            raise SamrPortalDownloadUnavailableError(detail)

        for attempt in range(1, max(max_attempts, 1) + 1):
            try:
                captcha_url = f"{base_url}/portal/validate-code?pk={pk}&t={int(time.time() * 1000)}"
                captcha = http.get(
                    captcha_url,
                    headers={
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        "Referer": online_url,
                    },
                )
                captcha.raise_for_status()
                content_type = (captcha.headers.get("content-type") or "").lower()
                if not content_type.startswith("image/") and not (
                    captcha.content.startswith(b"\x89PNG")
                    or captcha.content.startswith(b"\xff\xd8\xff")
                ):
                    raise SamrPortalCaptchaError(f"验证码接口返回异常：{content_type or 'unknown'}")

                verify_code = solve_captcha_image(captcha.content)
                verify = http.post(
                    f"{base_url}/portal/validate-captcha/down",
                    data={"captcha": verify_code, "pk": pk},
                    headers={
                        "Accept": "application/json,text/javascript,*/*;q=0.8",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": online_url,
                    },
                )
                verify.raise_for_status()
                try:
                    verify_payload = verify.json()
                except ValueError as exc:
                    raise SamrPortalCaptchaError("官方验证码校验接口返回异常") from exc
                if str(verify_payload.get("code")) != "0":
                    message = str(verify_payload.get("msg") or "验证码不正确")
                    raise SamrPortalCaptchaIncorrectError(message)

                download_token = str(verify_payload.get("msg") or "").strip()
                if not download_token:
                    raise SamrPortalCaptchaError("官方验证码校验未返回下载码")

                file_url = f"{base_url}/portal/download/{download_token}"
                response = http.get(
                    file_url,
                    headers={"Accept": "application/pdf,*/*", "Referer": online_url},
                )
                response.raise_for_status()
                if not response.content.startswith(b"%PDF"):
                    snippet = response.content[:200].decode("utf-8", errors="ignore")
                    raise SamrPortalDownloadUnavailableError(f"官方返回内容不是 PDF：{snippet[:120]!r}")

                return DownloadedContent(
                    status_code=response.status_code,
                    url=online_url,
                    content=response.content,
                    content_type=response.headers.get("content-type"),
                    content_disposition=response.headers.get("content-disposition"),
                )
            except SamrPortalCaptchaIncorrectError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise
                time.sleep(min(attempt, 3))
            except SamrPortalCaptchaError:
                raise
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise SamrPortalCaptchaError(f"sacinfo portal 下载失败：{exc}") from exc
                time.sleep(min(attempt, 3))

        raise SamrPortalCaptchaError(f"sacinfo portal 下载失败：{last_error}") from last_error
    finally:
        if owns_client:
            http.close()
