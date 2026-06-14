"""MOT (jtst.mot.gov.cn) official file discovery helpers."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

from app import models
from app.batch2_file_discovery import DiscoveredFile, pick_best_official_file
from app.batch2_http import fetch_html
from app.gb688_captcha_download import extract_hcno, openstd_download_page_url

MOT_BASE = "https://jtst.mot.gov.cn"
HCNO_RE = re.compile(r"hcno=([A-F0-9]+)", re.I)
LOCATION_S_RE = re.compile(r"location_s\s*=\s*['\"]([^'\"]+)['\"]")
MOT_TYPE_RE = re.compile(r"var\s+type\s*=\s*'([^']+)'", re.I)
MOT_PID_RE = re.compile(r"[?&]id=([0-9a-f]+)", re.I)

MOT_KFS_READ_PREFIX = f"{MOT_BASE}/kfs/file/read/"
MOT_KFS_DOWNLOAD_PREFIX = f"{MOT_BASE}/kfs/file/downloadStd/"


def _detail_pid(detail_url: str | None) -> str | None:
    if not detail_url:
        return None
    query = parse_qs(urlparse(detail_url).query)
    pid = (query.get("id") or [None])[0]
    if pid:
        return str(pid)
    match = MOT_PID_RE.search(detail_url)
    return match.group(1) if match else None


def _mot_type_from_html(html: str) -> str | None:
    match = MOT_TYPE_RE.search(html)
    return match.group(1).strip() if match else None


def _hcno_from_openpdf(html: str) -> str | None:
    block_match = re.search(r"\.openpdf[^\{]*\{[^}]+\}", html, re.I | re.S)
    block = block_match.group(0) if block_match else html
    match = HCNO_RE.search(block)
    return match.group(1) if match else None


def _location_s_from_std_hb_view(client: httpx.Client, pid: str) -> str | None:
    view_url = f"{MOT_BASE}/hb/search/stdHBView?id={pid}"
    html = fetch_html(client, view_url)
    match = LOCATION_S_RE.search(html)
    return match.group(1) if match else None


def discover_mot_official_file(
    client: httpx.Client,
    resource: models.StandardResource,
) -> DiscoveredFile | None:
    detail_url = (resource.detail_url or "").strip()
    if not detail_url or detail_url.rstrip("/") == MOT_BASE:
        return None

    html = fetch_html(client, detail_url)
    mot_type = _mot_type_from_html(html)
    pid = _detail_pid(detail_url)

    if mot_type == "BV_GB":
        hcno = _hcno_from_openpdf(html) or extract_hcno(html)
        if hcno:
            url = openstd_download_page_url(hcno)
            return DiscoveredFile(url=url, label=f"openstd:{hcno}", score=90)

    if mot_type in {"BV_HB", "BV_JJG_JT"} and pid:
        location_s = _location_s_from_std_hb_view(client, pid)
        if location_s:
            url = f"{MOT_KFS_DOWNLOAD_PREFIX}{location_s}"
            return DiscoveredFile(url=url, label=f"mot_kfs:{location_s}", score=85)

    hcno = _hcno_from_openpdf(html) or extract_hcno(html)
    if hcno:
        url = openstd_download_page_url(hcno)
        return DiscoveredFile(url=url, label=f"openstd:{hcno}", score=80)

    if pid and ("/hb/" in detail_url or mot_type == "BV_HB"):
        location_s = _location_s_from_std_hb_view(client, pid)
        if location_s:
            url = f"{MOT_KFS_DOWNLOAD_PREFIX}{location_s}"
            return DiscoveredFile(url=url, label=f"mot_kfs:{location_s}", score=75)

    return None
