"""URL 来源画像与治理决策（第二阶段）。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

from app.standard_number import PREFIX_PATTERN

GOV_PROFILED = "已画像"
GOV_HIGH_PRIORITY = "高优先级采集"
GOV_LOW_PRIORITY = "低优先级采集"
GOV_CLUE_ONLY = "只作线索"
GOV_NEED_OCR = "需 OCR"
GOV_NEED_LOGIN = "需登录"
GOV_NEED_ADAPTER = "需规则适配"
GOV_DUPLICATE = "重复待合并"
GOV_INVALID = "已标记失效"
GOV_PAUSED = "暂停采集"
GOV_BLACKLIST = "黑名单"

LEGACY_UNGOVERNED = frozenset({"pending", "profiled", "error", ""})
ALL_GOVERNANCE_STATUSES = frozenset(
    {
        GOV_PROFILED,
        GOV_HIGH_PRIORITY,
        GOV_LOW_PRIORITY,
        GOV_CLUE_ONLY,
        GOV_NEED_OCR,
        GOV_NEED_LOGIN,
        GOV_NEED_ADAPTER,
        GOV_DUPLICATE,
        GOV_INVALID,
        GOV_PAUSED,
        GOV_BLACKLIST,
    }
)

OFFICIAL_DOMAIN_SUFFIXES = (
    "samr.gov.cn",
    "std.samr.gov.cn",
    "openstd.samr.gov.cn",
    "c.gb688.cn",
    "ebook.chinabuilding.com.cn",
    "sacinfo.org.cn",
    "hbba.sacinfo.org.cn",
    "dbba.sacinfo.org.cn",
    "ttbz.org.cn",
    "qybz.org.cn",
    "spc.org.cn",
    "cnis.ac.cn",
    "chinabuilding.com.cn",
)

CLOUD_DRIVE_HOST_KEYWORDS = (
    "pan.baidu.com",
    "yun.baidu.com",
    "aliyundrive.com",
    "alipan.com",
    "pan.quark.cn",
    "quark.cn",
    "115.com",
    "weiyun.com",
    "jianguoyun.com",
    "123pan.com",
    "lanzou",
    "cowtransfer.com",
    "kdocs.cn",
    "365.kdocs.cn",
)

COMMERCIAL_HOST_KEYWORDS = (
    "doc88.com",
    "book118.com",
    "max.book118.com",
    "wenku.baidu.com",
    "ishuwenku.com",
    "antpedia.com",
    "bzfxw.com",
    "down6.com",
    "guifanku.com",
)

TRACKING_QUERY_KEYS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "from",
        "share_source",
        "spm",
        "fbclid",
        "gclid",
        "msclkid",
        "ref",
        "referrer",
    }
)

OFFICIAL_ID_QUERY_KEYS = ("hcno", "pk", "bookid", "book_id", "id", "stdid", "standardid", "no")

LOGIN_HINTS = ("login", "passport", "oauth", "needlogin", "signin", "auth", "sso")
CAPTCHA_HINTS = ("captcha", "verifycode", "verification", "geetest", "slideverify", "randcode")
LIST_PAGE_HINTS = ("/list", "/search", "/query", "/index", "pagelist", "getlist", "catalog")
DETAIL_PAGE_HINTS = (
    "/detail",
    "/showgb",
    "/newgbinfo",
    "/gbdetailed",
    "/book/show",
    "/standard/detail",
    "/std/detail",
    "type=online",
    "type=download",
    "hcno=",
    "newinfo",
)
DOWNLOAD_PAGE_HINTS = ("type=download", "/download", "download.do", "getfile", "downfile")

STANDARD_NO_IN_URL = re.compile(
    r"(?i)(?:GB/T|GB/Z|GB|JGJ/T|JGJ|CJJ/T|CJJ|CECS|DB\d{0,2}/T|DB\d{0,2}|T/[A-Z0-9]+|[A-Z]{2,8}/T|[A-Z]{2,8})"
    r"[\s\-_/]*[\d]+(?:[\.\-][\d]+)*(?:[\-\(（][^/\?#]{0,40}[\)）])?(?:[\-\./_]*(?:19|20)\d{2})?",
)


@dataclass(frozen=True)
class UrlProfile:
    url: str
    host: str | None = None
    domain: str | None = None
    file_ext: str | None = None
    is_https: bool = False
    is_pdf: bool = False
    is_word: bool = False
    is_excel: bool = False
    is_html: bool = False
    is_cloud_drive: bool = False
    is_official_domain: bool = False
    is_detail_page: bool = False
    is_download_page: bool = False
    is_list_page: bool = False
    is_api_endpoint: bool = False
    is_commercial_site: bool = False
    is_login_required_hint: bool = False
    is_captcha_hint: bool = False
    has_standard_no: bool = False
    standard_no_hint: str | None = None
    url_type: str = "unknown"
    duplicate_group_key: str | None = None
    normalized_url: str | None = None
    invalid_reason: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_host(host: str | None) -> str | None:
    if not host:
        return None
    return host.lower().strip(".")


def _host_matches_suffix(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


def is_official_host(host: str | None, *, extra_domains: set[str] | None = None) -> bool:
    host = _normalize_host(host)
    if not host:
        return False
    for suffix in OFFICIAL_DOMAIN_SUFFIXES:
        if _host_matches_suffix(host, suffix):
            return True
    if extra_domains:
        for domain in extra_domains:
            domain = _normalize_host(domain)
            if domain and (host == domain or _host_matches_suffix(host, domain)):
                return True
    return False


def _extract_file_ext(path: str) -> str | None:
    path = unquote(path or "")
    if "." not in path:
        return None
    ext = path.rsplit(".", 1)[-1].lower().strip()
    if not ext or len(ext) > 12 or not re.fullmatch(r"[a-z0-9]+", ext):
        return None
    return ext


def _detect_standard_no(text: str) -> str | None:
    match = STANDARD_NO_IN_URL.search(text)
    if match:
        return match.group(0).strip()
    match = PREFIX_PATTERN.search(text.upper().replace("／", "/"))
    if match:
        return match.group(0)
    return None


def _strip_tracking_params(parsed) -> list[tuple[str, str]]:
    query = parse_qs(parsed.query, keep_blank_values=False)
    filtered = {k: v for k, v in query.items() if k.lower() not in TRACKING_QUERY_KEYS}
    flat: list[tuple[str, str]] = []
    for key in sorted(filtered.keys()):
        for value in filtered[key]:
            flat.append((key, value))
    return flat


def _extract_official_identity(parsed, host: str) -> str | None:
    query = parse_qs(parsed.query, keep_blank_values=False)
    parts: list[str] = []
    for key in OFFICIAL_ID_QUERY_KEYS:
        values = query.get(key) or query.get(key.upper()) or query.get(key.lower())
        if values:
            parts.append(f"{key.lower()}={values[0].lower()}")
    if parts:
        return "|".join(sorted(parts))
    if is_official_host(host):
        path = unquote(parsed.path or "").rstrip("/").lower()
        if path and path != "/":
            return f"path={path}"
    return None


def _extract_baidu_share_identity(url: str, parsed) -> str | None:
    host = _normalize_host(parsed.hostname) or ""
    if "pan.baidu.com" not in host and "yun.baidu.com" not in host:
        return None
    path = unquote(parsed.path or "")
    share_path = re.search(r"/s/1([A-Za-z0-9_-]+)", path)
    if share_path:
        return f"baidu_share={share_path.group(1).lower()}"
    query = parse_qs(parsed.query, keep_blank_values=False)
    for key in ("surl", "shareid", "share_id", "fid"):
        if query.get(key):
            return f"baidu_{key}={query[key][0].lower()}"
    return None


def normalize_url_for_dedupe(url: str) -> str:
    parsed = urlparse(url.strip())
    host = _normalize_host(parsed.hostname) or ""
    path = unquote(parsed.path or "/").rstrip("/") or "/"
    path = re.sub(r"/+", "/", path.lower())
    query_pairs = _strip_tracking_params(parsed)
    query = urlencode(query_pairs, doseq=True)
    return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))


def build_duplicate_group_key(url: str) -> str | None:
    try:
        parsed = urlparse(url.strip())
        host = _normalize_host(parsed.hostname) or ""
        if not host:
            return None
        identity_parts = [host, unquote(parsed.path or "/").rstrip("/").lower() or "/"]
        baidu_id = _extract_baidu_share_identity(url, parsed)
        if baidu_id:
            identity_parts.append(baidu_id)
        else:
            official_id = _extract_official_identity(parsed, host)
            if official_id:
                identity_parts.append(official_id)
            else:
                query_pairs = _strip_tracking_params(parsed)
                if query_pairs:
                    identity_parts.append(urlencode(sorted(query_pairs)))
        raw = "||".join(identity_parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    except Exception:
        return None


def extract_url_profile(url: str, *, extra_official_domains: set[str] | None = None) -> UrlProfile:
    raw = (url or "").strip()
    if not raw or raw.lower().startswith(("javascript:", "mailto:", "tel:", "data:")):
        return UrlProfile(url=raw, url_type="invalid", invalid_reason="unsupported_or_empty_scheme")

    try:
        parsed = urlparse(raw)
    except Exception:
        return UrlProfile(url=raw, url_type="invalid", invalid_reason="parse_failed")

    host = _normalize_host(parsed.hostname)
    if not host:
        return UrlProfile(url=raw, url_type="invalid", invalid_reason="missing_host")

    path = unquote(parsed.path or "")
    lowered = raw.lower()
    file_ext = _extract_file_ext(path)
    scheme = (parsed.scheme or "").lower()
    is_https = scheme == "https"

    is_pdf = file_ext == "pdf" or ".pdf" in lowered or "/pdf/" in lowered
    is_word = file_ext in {"doc", "docx", "wps"} or any(x in lowered for x in (".doc", ".docx"))
    is_excel = file_ext in {"xls", "xlsx", "csv"} or any(x in lowered for x in (".xls", ".xlsx"))
    is_html = file_ext in {"html", "htm", "shtml"} or path.endswith("/") or not file_ext

    is_cloud = any(k in host for k in CLOUD_DRIVE_HOST_KEYWORDS)
    is_official = is_official_host(host, extra_domains=extra_official_domains)
    is_commercial = any(k in host for k in COMMERCIAL_HOST_KEYWORDS)

    is_detail = any(h in lowered for h in DETAIL_PAGE_HINTS)
    is_download = any(h in lowered for h in DOWNLOAD_PAGE_HINTS)
    is_list = any(h in lowered for h in LIST_PAGE_HINTS)
    query_keys = {k.lower() for k in parse_qs(parsed.query)}
    is_api = bool(query_keys & {"method", "action", "api", "op"}) or "/api/" in lowered

    is_login_hint = any(h in lowered for h in LOGIN_HINTS)
    is_captcha_hint = any(h in lowered for h in CAPTCHA_HINTS) or ("gb688" in host and "download" in lowered)

    std_no = _detect_standard_no(raw)
    normalized = normalize_url_for_dedupe(raw)
    dup_key = build_duplicate_group_key(raw)

    base = UrlProfile(
        url=raw,
        host=host,
        domain=host,
        file_ext=file_ext,
        is_https=is_https,
        is_pdf=is_pdf,
        is_word=is_word,
        is_excel=is_excel,
        is_html=is_html,
        is_cloud_drive=is_cloud,
        is_official_domain=is_official,
        is_detail_page=is_detail,
        is_download_page=is_download,
        is_list_page=is_list,
        is_api_endpoint=is_api,
        is_commercial_site=is_commercial,
        is_login_required_hint=is_login_hint,
        is_captcha_hint=is_captcha_hint,
        has_standard_no=bool(std_no),
        standard_no_hint=std_no,
        normalized_url=normalized,
        duplicate_group_key=dup_key,
    )
    url_type = classify_url_type(base)
    return UrlProfile(**{**base.to_dict(), "url_type": url_type})


def classify_url_type(profile: UrlProfile) -> str:
    if profile.invalid_reason or not profile.host:
        return "invalid"
    if profile.is_login_required_hint and not profile.is_official_domain:
        return "login_required"
    if profile.is_captcha_hint or ("gb688" in (profile.host or "") and profile.is_download_page):
        return "captcha_download"
    if profile.is_cloud_drive:
        return "cloud_drive"
    if profile.is_official_domain:
        if profile.is_pdf:
            return "official_pdf"
        if profile.is_detail_page or profile.is_download_page:
            return "official_detail"
        if profile.is_list_page or profile.is_api_endpoint:
            return "official_list"
        if profile.is_html:
            return "official_detail"
    if profile.is_api_endpoint:
        return "api_endpoint"
    if profile.is_commercial_site:
        return "commercial_page"
    if profile.is_pdf or profile.is_word or profile.is_excel:
        return "document_page"
    if profile.is_detail_page:
        return "document_page"
    if profile.is_list_page:
        return "commercial_page"
    return "unknown"


def calculate_source_quality_score(profile: UrlProfile) -> int:
    if profile.url_type == "invalid":
        return 0

    score = 15
    if profile.is_https:
        score += 5
    if profile.is_official_domain:
        score += 30
    if profile.url_type == "official_pdf":
        score += 30
    elif profile.url_type == "official_detail":
        score += 22
    elif profile.url_type == "official_list":
        score += 12
    elif profile.url_type == "document_page":
        score += 12
    elif profile.url_type == "cloud_drive":
        score += 8
    elif profile.url_type == "commercial_page":
        score += 5

    if profile.has_standard_no:
        score += 8
    if profile.is_pdf:
        score += 5
    if profile.file_ext in {"doc", "docx", "xls", "xlsx"}:
        score += 3

    if profile.url_type in {"login_required", "captcha_download"}:
        score += 10
    if profile.url_type == "unknown":
        score -= 10
    if profile.url_type == "commercial_page" and not profile.has_standard_no:
        score -= 8
    if profile.is_cloud_drive and not profile.has_standard_no:
        score -= 5
    if not profile.is_https and profile.is_official_domain:
        score -= 3

    return max(0, min(100, score))


def decide_governance_status(
    profile: UrlProfile,
    score: int,
    *,
    is_duplicate: bool = False,
    source_link_status: str | None = None,
) -> str:
    if profile.url_type == "invalid" or score <= 0:
        return GOV_INVALID
    if source_link_status in {"失效", "异常"}:
        return GOV_INVALID
    if is_duplicate:
        return GOV_DUPLICATE
    if profile.url_type == "login_required" or profile.is_login_required_hint:
        return GOV_NEED_LOGIN
    if profile.url_type == "captcha_download":
        return GOV_NEED_OCR
    if profile.url_type == "api_endpoint":
        return GOV_NEED_ADAPTER

    if profile.url_type == "official_pdf" and score >= 70:
        return GOV_HIGH_PRIORITY
    if profile.url_type == "official_detail" and score >= 65:
        return GOV_HIGH_PRIORITY
    if profile.url_type in {"official_list", "official_pdf"} and score >= 55:
        return GOV_LOW_PRIORITY
    if profile.url_type == "document_page" and profile.is_official_domain:
        return GOV_LOW_PRIORITY
    if profile.url_type == "cloud_drive":
        return GOV_CLUE_ONLY if score >= 35 else GOV_PAUSED
    if profile.url_type == "commercial_page":
        return GOV_CLUE_ONLY if profile.has_standard_no else GOV_PAUSED
    if profile.url_type == "unknown":
        return GOV_CLUE_ONLY if profile.has_standard_no else GOV_PAUSED
    if score >= 75:
        return GOV_HIGH_PRIORITY
    if score >= 50:
        return GOV_LOW_PRIORITY
    if score >= 30:
        return GOV_CLUE_ONLY
    if score < 15:
        return GOV_BLACKLIST
    return GOV_PROFILED


def is_ungoverned_status(status: str | None) -> bool:
    value = (status or "").strip()
    return value in LEGACY_UNGOVERNED or value not in ALL_GOVERNANCE_STATUSES


def profile_url_source_row(
    url: str,
    *,
    extra_official_domains: set[str] | None = None,
    is_duplicate: bool = False,
    source_link_status: str | None = None,
) -> dict:
    profile = extract_url_profile(url, extra_official_domains=extra_official_domains)
    score = calculate_source_quality_score(profile)
    governance_status = decide_governance_status(
        profile,
        score,
        is_duplicate=is_duplicate,
        source_link_status=source_link_status,
    )
    return {
        "host": profile.host,
        "url_type": profile.url_type,
        "file_ext": profile.file_ext,
        "is_official_domain": profile.is_official_domain,
        "is_cloud_drive": profile.is_cloud_drive,
        "is_probable_pdf": profile.is_pdf,
        "is_probable_detail_page": profile.is_detail_page or profile.is_download_page,
        "source_quality_score": score,
        "governance_status": governance_status,
        "duplicate_group_key": profile.duplicate_group_key,
        "profile": profile,
        "score": score,
    }


SAMPLE_FILTERS = {
    "official_domains": lambda p: p.is_official_domain,
    "pdf_links": lambda p: p.is_pdf or p.file_ext == "pdf",
    "cloud_drive": lambda p: p.is_cloud_drive or p.url_type == "cloud_drive",
    "commercial_sites": lambda p: p.is_commercial_site or p.url_type == "commercial_page",
    "unknown": lambda p: p.url_type == "unknown",
}
