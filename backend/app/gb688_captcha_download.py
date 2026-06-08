from __future__ import annotations

import os
import re
import time
from functools import lru_cache

import httpx

from app.download_service import DownloadedContent

OPENSTD_STD_BASE = "https://openstd.samr.gov.cn/bzgk/std"
OPENSTD_SITE = "https://openstd.samr.gov.cn"
LEGACY_GB688_BASE = "http://c.gb688.cn/bzgk/gb"
HCNO_RE = re.compile(r"hcno=([A-Za-z0-9]+)", re.I)


class OpenstdCaptchaError(RuntimeError):
    pass


class OpenstdCaptchaIncorrectError(OpenstdCaptchaError):
    pass


class OpenstdDownloadUnavailableError(OpenstdCaptchaError):
    pass


Gb688CaptchaError = OpenstdCaptchaError
Gb688CaptchaIncorrectError = OpenstdCaptchaIncorrectError
Gb688DownloadUnavailableError = OpenstdDownloadUnavailableError


def extract_hcno(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        match = HCNO_RE.search(value)
        if match:
            return match.group(1)
    return None


def openstd_download_page_url(hcno: str) -> str:
    return f"{OPENSTD_STD_BASE}/showGb?type=download&hcno={hcno}"


def openstd_online_page_url(hcno: str) -> str:
    return f"{OPENSTD_STD_BASE}/showGb?type=online&hcno={hcno}"


def openstd_file_url(hcno: str) -> str:
    return f"{OPENSTD_STD_BASE}/viewGb?hcno={hcno}"


def openstd_detail_url(hcno: str) -> str:
    return f"{OPENSTD_SITE}/bzgk/std/newGbInfo?hcno={hcno}"


def openstd_review_url(hcno: str) -> str:
    return f"{OPENSTD_SITE}/bzgk/gb/review?hcno={hcno}"


def legacy_download_page_url(hcno: str) -> str:
    return f"{LEGACY_GB688_BASE}/showGb?type=download&hcno={hcno}&request_locale=zh"


def legacy_online_page_url(hcno: str) -> str:
    return f"{LEGACY_GB688_BASE}/showGb?type=online&hcno={hcno}&request_locale=zh"


def legacy_file_url(hcno: str) -> str:
    return f"{LEGACY_GB688_BASE}/viewGb?hcno={hcno}"


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


@lru_cache(maxsize=1)
def _ocr_instance():
    try:
        import ddddocr
    except ImportError as exc:
        raise OpenstdCaptchaError("ddddocr 未安装，无法自动识别验证码") from exc
    return ddddocr.DdddOcr(show_ad=False)


def solve_captcha_image(image_bytes: bytes) -> str:
    raw = _ocr_instance().classification(image_bytes)
    code = re.sub(r"[^0-9A-Za-z]", "", raw or "").strip()
    if not code:
        raise OpenstdCaptchaError(f"验证码识别结果为空：{raw!r}")
    return code[:8]


def _download_with_endpoints(
    http: httpx.Client,
    *,
    hcno: str,
    std_base: str,
    download_page_url: str,
    online_page_url: str,
    max_attempts: int,
) -> DownloadedContent:
    verify_url = f"{std_base}/verifyCode"
    captcha_url = f"{std_base}/gc"
    file_url = f"{std_base}/viewGb?hcno={hcno}"
    last_error: Exception | None = None

    for attempt in range(1, max(max_attempts, 1) + 1):
        try:
            page = http.get(download_page_url, headers={"Accept": "text/html,*/*", "Referer": online_page_url})
            if page.status_code == 404:
                raise OpenstdDownloadUnavailableError(f"下载页不存在：{download_page_url}")
            page.raise_for_status()

            captcha = http.get(
                captcha_url,
                headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8", "Referer": download_page_url},
            )
            captcha.raise_for_status()
            content_type = captcha.headers.get("content-type") or ""
            if not content_type.lower().startswith("image/"):
                raise OpenstdCaptchaError(f"验证码接口返回异常：{content_type}")

            verify_code = solve_captcha_image(captcha.content)
            verify = http.post(
                verify_url,
                data={"verifyCode": verify_code},
                headers={
                    "Accept": "text/plain,*/*",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": download_page_url,
                },
            )
            verify.raise_for_status()
            if verify.text.strip() != "success":
                raise OpenstdCaptchaIncorrectError(f"验证码不正确：{verify_code!r}")

            response = http.get(file_url, headers={"Accept": "application/pdf,*/*", "Referer": download_page_url})
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                snippet = response.content[:200].decode("utf-8", errors="ignore")
                raise OpenstdDownloadUnavailableError(f"官方返回内容不是 PDF：{snippet[:120]!r}")

            return DownloadedContent(
                status_code=response.status_code,
                url=str(response.url),
                content=response.content,
                content_type=response.headers.get("content-type"),
                content_disposition=response.headers.get("content-disposition"),
            )
        except OpenstdCaptchaIncorrectError as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise
            time.sleep(min(attempt, 3))
        except OpenstdCaptchaError:
            raise
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise OpenstdCaptchaError(f"openstd 下载失败：{exc}") from exc
            time.sleep(min(attempt, 3))

    raise OpenstdCaptchaError(f"openstd 下载失败：{last_error}") from last_error


def download_openstd_pdf(
    hcno: str,
    *,
    timeout_seconds: int = 60,
    max_attempts: int = 3,
    client: httpx.Client | None = None,
) -> DownloadedContent:
    hcno = (hcno or "").strip()
    if not hcno:
        raise OpenstdDownloadUnavailableError("缺少 hcno，无法下载")

    owns_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout_seconds, headers=_default_headers())
    try:
        try:
            return _download_with_endpoints(
                http,
                hcno=hcno,
                std_base=OPENSTD_STD_BASE,
                download_page_url=openstd_download_page_url(hcno),
                online_page_url=openstd_online_page_url(hcno),
                max_attempts=max_attempts,
            )
        except OpenstdDownloadUnavailableError as openstd_error:
            message = str(openstd_error)
            if "404" not in message and "不存在" not in message:
                raise
            return _download_with_endpoints(
                http,
                hcno=hcno,
                std_base=LEGACY_GB688_BASE,
                download_page_url=legacy_download_page_url(hcno),
                online_page_url=legacy_online_page_url(hcno),
                max_attempts=max_attempts,
            )
    finally:
        if owns_client:
            http.close()


def download_openstd_pdf_from_row(
    row: dict,
    *,
    timeout_seconds: int = 60,
    max_attempts: int | None = None,
    client: httpx.Client | None = None,
) -> DownloadedContent:
    hcno = extract_hcno(str(row.get("OPEN_HASH_CODE") or ""))
    if not hcno:
        raise OpenstdDownloadUnavailableError("no OPEN_HASH_CODE")
    attempts = max_attempts if max_attempts is not None else int(os.getenv("OPENSTD_CAPTCHA_MAX_ATTEMPTS", "3"))
    return download_openstd_pdf(hcno, timeout_seconds=timeout_seconds, max_attempts=attempts, client=client)


download_gb688_pdf = download_openstd_pdf
download_gb688_pdf_from_row = download_openstd_pdf_from_row
