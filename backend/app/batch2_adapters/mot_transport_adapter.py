"""交通运输部交通运输标准化信息系统 adapter."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app import models
from app.batch2_adapters.base import (
    CategoryConfig,
    ParsedListItem,
    StandardCatalogAdapterMixin,
    TrustedSourceSearchQuery,
    TrustedSourceSearchResult,
    TrustedSourceSyncOptions,
    TrustedSourceSyncStats,
    absolute_url,
    build_search_result,
    delay,
    detail_hash,
    ensure_single_category,
    external_search_keyword,
    extract_standard_no_from_title,
    fetch_html,
    finalize_category_sync,
    make_client,
    now_utc,
    paginate_indices,
    parse_html_list_items,
)
from app.trusted_source_adapters import registry

MOT_BASE = "https://jtst.mot.gov.cn"
MOT_STD_PAGE = f"{MOT_BASE}/search/std"
MOT_SEARCH_KEYWORDS = ("", "JTG", "JT/T", "GB/T", "JT", "公路", "港口", "水运", "物流", "安全")
MOT_STD_ROW_PATTERN = re.compile(r"(?:GB/T|JT/T|JTG|JT\s*/?\s*T)\s*[\d./-]+", re.IGNORECASE)


def parse_mot_stdpage_items(html: str, *, resource_type: str) -> list[ParsedListItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[ParsedListItem] = []
    seen: set[str] = set()
    for row in soup.select("table tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        title = re.sub(r"\s+", " ", cells[0]).strip()
        if not MOT_STD_ROW_PATTERN.search(title):
            continue
        anchor = row.find("a", href=True)
        detail_url = absolute_url(MOT_BASE, anchor["href"]) if anchor else None
        item_id = detail_hash({"title": title, "url": detail_url})
        if item_id in seen:
            continue
        seen.add(item_id)
        source_status = cells[1].strip() if len(cells) > 1 else None
        items.append(
            ParsedListItem(
                item_id=item_id,
                title=title,
                detail_url=detail_url,
                standard_no=extract_standard_no_from_title(title),
                source_status=source_status,
                summary=" | ".join(cells[1:3]) if len(cells) > 1 else None,
                resource_type=resource_type,
                raw={"title": title, "url": detail_url, "status": source_status},
            )
        )
    return items


class MotTransportAdapter(StandardCatalogAdapterMixin):
    adapter_key = "mot_transport_standard_public"

    config = CategoryConfig(
        "transport_standard",
        "交通运输标准",
        "交通运输部 / 交通运输标准化信息系统",
        MOT_STD_PAGE,
    )

    def _keyword_for_page(self, page: int) -> str:
        return MOT_SEARCH_KEYWORDS[(page - 1) % len(MOT_SEARCH_KEYWORDS)]

    def _fetch_page(self, client, page: int) -> tuple[list[ParsedListItem], int | None]:
        keyword = self._keyword_for_page(page)
        url = f"{MOT_BASE}/search/stdPage?q={keyword}"
        html = fetch_html(client, url)
        items = parse_mot_stdpage_items(html, resource_type=self.config.category_name)
        if items:
            return items, None
        fallback = parse_html_list_items(html, MOT_BASE, resource_type=self.config.category_name)
        return fallback, None

    def sync(self, db: Session, source_id: int, options: TrustedSourceSyncOptions) -> TrustedSourceSyncStats:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise ValueError(f"trusted source not found: {source_id}")
        category = ensure_single_category(db, source, self.config)
        db.commit()

        stats = TrustedSourceSyncStats(categories=1)
        start_page = max(1, (category.last_synced_page or 0) + 1) if options.only_pending_categories else 1
        category.sync_status = "同步中"
        category.last_sync_started_at = now_utc()
        category.last_sync_error = None
        db.commit()

        errors = 0
        last_page = start_page - 1
        seen_ids: set[str] = set()
        with make_client(referer=MOT_STD_PAGE) as client:
            for page_number in paginate_indices(start_page, options.max_pages):
                try:
                    items, _total = self._fetch_page(client, page_number)
                except Exception as exc:
                    errors += 1
                    category.last_sync_error = str(exc)[:500]
                    break
                fresh_items = [item for item in items if item.item_id not in seen_ids]
                if not fresh_items and page_number > start_page:
                    break
                for item in items:
                    seen_ids.add(item.item_id)
                if not fresh_items:
                    continue
                last_page = page_number
                stats.pages += 1
                self._persist_items(db, source, category, fresh_items, stats)
                db.commit()
                delay()
        if seen_ids:
            category.resource_count = len(seen_ids)
        finalize_category_sync(db, category, stats, errors=errors, page_number=last_page, total_pages=None)
        return stats

    def _search_external_impl(
        self, db: Session, source_id: int, query: TrustedSourceSearchQuery
    ) -> list[TrustedSourceSearchResult]:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            return []
        keyword = external_search_keyword(query)
        if not keyword:
            return []
        with make_client(referer=MOT_STD_PAGE) as client:
            html = fetch_html(client, f"{MOT_BASE}/search/stdPage?q={keyword}")
            items = parse_mot_stdpage_items(html, resource_type=self.config.category_name)
            if not items:
                items = parse_html_list_items(html, MOT_BASE, resource_type=self.config.category_name)
        return [
            build_search_result(
                source,
                adapter_key=self.adapter_key,
                item_id=item.item_id,
                standard_no=item.standard_no,
                standard_name=item.title,
                source_status=item.source_status,
                detail_url=item.detail_url,
                publish_date=item.publish_date,
                effective_date=item.effective_date,
                query=query,
            )
            for item in items[:20]
        ]


registry.register(MotTransportAdapter())
