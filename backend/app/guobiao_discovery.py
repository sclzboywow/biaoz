from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app import models

BASE_URL = "https://ebook.chinabuilding.com.cn"
DISCOVERY_URL = f"{BASE_URL}/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView"


@dataclass
class DiscoveredSublib:
    sublib_id: str
    category_name: str
    category_path: str
    source_url: str


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _sublib_id_from_href(href: str | None) -> str | None:
    if not href:
        return None
    match = re.search(r"sublibID=(\d+)", href)
    return match.group(1) if match else None


def _direct_category_anchor(li) -> object | None:
    for anchor in li.find_all("a", recursive=False):
        href = anchor.get("href")
        if _sublib_id_from_href(href):
            return anchor
    return None


def _path_for_anchor(anchor) -> str:
    parts: list[str] = []
    for parent in reversed(anchor.find_parents("li")):
        direct_anchor = _direct_category_anchor(parent)
        if not direct_anchor:
            continue
        text = _clean_text(direct_anchor.get_text(" ", strip=True))
        if text and (not parts or parts[-1] != text):
            parts.append(text)
    own_text = _clean_text(anchor.get_text(" ", strip=True))
    if own_text and (not parts or parts[-1] != own_text):
        parts.append(own_text)
    return " / ".join(parts)


def discover_guobiao_sublibs(timeout_seconds: int = 30) -> list[DiscoveredSublib]:
    with httpx.Client(follow_redirects=True, timeout=timeout_seconds, headers={"User-Agent": "Mozilla/5.0"}) as client:
        response = client.get(DISCOVERY_URL)
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    discovered: dict[str, DiscoveredSublib] = {}

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        sublib_id = _sublib_id_from_href(href)
        if not sublib_id:
            continue
        name = _clean_text(anchor.get_text(" ", strip=True))
        if not name or name in {"全部资源分类", "首页"}:
            continue
        source_url = urljoin(BASE_URL, href)
        category_path = _path_for_anchor(anchor) or name
        discovered[sublib_id] = DiscoveredSublib(
            sublib_id=sublib_id,
            category_name=name,
            category_path=category_path,
            source_url=source_url,
        )

    return sorted(discovered.values(), key=lambda item: int(item.sublib_id))


def sync_discovered_sublibs(db: Session, source: models.TrustedSource) -> dict[str, int]:
    items = discover_guobiao_sublibs()
    created = 0
    updated = 0
    now = datetime.now(UTC)
    existing_by_sublib = {
        item.source_category_id: item
        for item in db.query(models.SourceCategory).filter(models.SourceCategory.source_id == source.id).all()
    }
    for item in items:
        existing = existing_by_sublib.get(item.sublib_id)
        if existing is None:
            db.add(
                models.SourceCategory(
                    source_id=source.id,
                    source_category_id=item.sublib_id,
                    category_name=item.category_name,
                    category_path=item.category_path,
                    source_url=item.source_url,
                    last_synced_at=now,
                    sync_status="待同步",
                )
            )
            created += 1
        else:
            changed = (
                existing.category_name != item.category_name
                or existing.category_path != item.category_path
                or existing.source_url != item.source_url
            )
            existing.category_name = item.category_name
            existing.category_path = item.category_path
            existing.source_url = item.source_url
            existing.last_synced_at = now
            if changed and existing.sync_status == "已同步":
                existing.sync_status = "待同步"
            updated += 1
    db.commit()
    return {"discovered": len(items), "created": created, "updated": updated}
