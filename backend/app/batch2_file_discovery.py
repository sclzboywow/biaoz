"""Discover official standard body files from batch-2 detail pages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app import models
from app.batch2_http import absolute_url, fetch_html, make_client
from app.batch2_admission import is_supported_official_file_url
from app.standard_number import normalize_standard_no

FILE_LINK_PATTERN = re.compile(r"\.(pdf|doc|docx|xls|xlsx)(?:\?|#|$)", re.I)
DOWNLOAD_HINTS = ("下载", "全文", "附件", "标准文本", "正文", "PDF", "pdf")


@dataclass(frozen=True)
class DiscoveredFile:
    url: str
    label: str
    score: int


def _link_score(label: str, href: str, *, standard_no: str | None) -> int:
    score = 0
    lowered = f"{label} {href}".lower()
    if FILE_LINK_PATTERN.search(href):
        score += 40
    if any(hint.lower() in lowered for hint in DOWNLOAD_HINTS):
        score += 20
    if standard_no:
        token = normalize_standard_no(standard_no).normalized or standard_no
        if token and token.upper() in f"{label} {href}".upper():
            score += 30
    if "公告" in label or "征求意见" in label or "目录" in label:
        score -= 50
    return score


def discover_official_files_from_html(html: str, base_url: str) -> list[DiscoveredFile]:
    soup = BeautifulSoup(html, "html.parser")
    discovered: list[DiscoveredFile] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = absolute_url(base_url, anchor["href"])
        if not href or href in seen:
            continue
        seen.add(href)
        label = anchor.get_text(" ", strip=True) or href
        if not (FILE_LINK_PATTERN.search(href) or any(h in label for h in DOWNLOAD_HINTS)):
            continue
        if not is_supported_official_file_url(href, file_name=label):
            continue
        discovered.append(DiscoveredFile(url=href, label=label[:200], score=_link_score(label, href, standard_no=None)))
    for tag in soup.find_all(["iframe", "embed", "source"]):
        src = tag.get("src")
        if not src:
            continue
        href = absolute_url(base_url, src)
        if href in seen:
            continue
        if is_supported_official_file_url(href):
            seen.add(href)
            discovered.append(DiscoveredFile(url=href, label=href, score=25))
    discovered.sort(key=lambda item: item.score, reverse=True)
    return discovered


def pick_best_official_file(
    files: list[DiscoveredFile],
    *,
    standard_no: str | None,
    standard_name: str | None,
) -> DiscoveredFile | None:
    if not files:
        return None
    rescored: list[DiscoveredFile] = []
    for item in files:
        score = item.score + _link_score(item.label, item.url, standard_no=standard_no)
        if standard_name and standard_name[:12] in item.label:
            score += 15
        rescored.append(DiscoveredFile(url=item.url, label=item.label, score=score))
    rescored.sort(key=lambda entry: entry.score, reverse=True)
    best = rescored[0]
    return best if best.score >= 30 else None


def discover_official_file_for_resource(
    client: httpx.Client,
    resource: models.StandardResource,
) -> DiscoveredFile | None:
    detail_url = (resource.detail_url or "").strip()
    if not detail_url:
        return None
    if "jtst.mot.gov.cn" in detail_url:
        from app.batch2_mot_file_discovery import discover_mot_official_file

        picked = discover_mot_official_file(client, resource)
        if picked is not None:
            return picked
    base = f"{urlparse(detail_url).scheme}://{urlparse(detail_url).netloc}"
    html = fetch_html(client, detail_url)
    files = discover_official_files_from_html(html, base)
    return pick_best_official_file(files, standard_no=resource.standard_no, standard_name=resource.standard_name)


def discover_official_file_url(
    resource: models.StandardResource,
    *,
    referer: str | None = None,
) -> str | None:
    detail_url = (resource.detail_url or "").strip()
    if not detail_url:
        return None
    with make_client(referer=referer or detail_url) as client:
        picked = discover_official_file_for_resource(client, resource)
    return picked.url if picked else None
