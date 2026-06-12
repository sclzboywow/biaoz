"""Generic government announcement list adapter."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import models
from app.batch2_adapters.base import (
    AnnouncementCatalogAdapterMixin,
    CategoryConfig,
    TrustedSourceSyncOptions,
    TrustedSourceSyncStats,
    ensure_single_category,
    fetch_html,
    finalize_category_sync,
    make_client,
    now_utc,
    parse_html_list_items,
)
from app.trusted_source_adapters import registry


@dataclass(frozen=True)
class AnnouncementSourceConfig:
    adapter_key: str
    category_id: str
    category_name: str
    category_path: str
    base_url: str
    list_urls: tuple[str, ...]
    announce_types: tuple[str, ...] = ("标准公告", "征求意见", "废止目录")


class GovAnnouncementAdapter(AnnouncementCatalogAdapterMixin):
    def __init__(self, config: AnnouncementSourceConfig) -> None:
        self.adapter_key = config.adapter_key
        self.config = CategoryConfig(
            config.category_id,
            config.category_name,
            config.category_path,
            config.list_urls[0],
        )
        self.base_url = config.base_url.rstrip("/")
        self.list_urls = config.list_urls
        self.announce_types = config.announce_types

    def sync(self, db: Session, source_id: int, options: TrustedSourceSyncOptions) -> TrustedSourceSyncStats:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise ValueError(f"trusted source not found: {source_id}")
        category = ensure_single_category(db, source, self.config)
        db.commit()

        stats = TrustedSourceSyncStats(categories=1)
        category.sync_status = "同步中"
        category.last_sync_started_at = now_utc()
        category.last_sync_error = None
        db.commit()

        errors = 0
        seen_titles: set[str] = set()
        with make_client(referer=self.list_urls[0]) as client:
            try:
                for list_url in self.list_urls[: max(1, options.max_pages)]:
                    html = fetch_html(client, list_url)
                    items = parse_html_list_items(html, self.base_url, resource_type=self.announce_types[0])
                    stats.pages += 1
                    for parsed in items:
                        if parsed.title in seen_titles:
                            continue
                        seen_titles.add(parsed.title)
                        announce_type = self.announce_types[0]
                        lowered = parsed.title
                        if "征求意见" in lowered:
                            announce_type = "征求意见"
                        elif any(token in lowered for token in ("废止", "失效", "作废")):
                            announce_type = "废止目录"
                        elif any(token in lowered for token in ("计划", "目录", "公告")):
                            announce_type = "标准公告"
                        self._upsert_announcement(
                            db,
                            source,
                            category,
                            title=parsed.title,
                            detail_url=parsed.detail_url,
                            announce_type=announce_type,
                            publish_date=parsed.publish_date,
                            summary=parsed.summary,
                            stats=stats,
                        )
                db.commit()
                category.resource_count = stats.items
            except Exception as exc:
                errors = 1
                category.last_sync_error = str(exc)[:500]
        finalize_category_sync(db, category, stats, errors=errors, page_number=stats.pages or 1, total_pages=1)
        return stats

    def _search_external_impl(self, db, source_id, query):
        return []


def register_announcement_adapter(config: AnnouncementSourceConfig) -> GovAnnouncementAdapter:
    adapter = GovAnnouncementAdapter(config)
    registry.register(adapter)
    return adapter
