"""自然资源标准化信息服务平台 adapter."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import models
from app.batch2_adapters.base import (
    CategoryConfig,
    StandardCatalogAdapterMixin,
    TrustedSourceSearchQuery,
    TrustedSourceSearchResult,
    TrustedSourceSyncOptions,
    TrustedSourceSyncStats,
    build_search_result,
    ensure_single_category,
    external_search_keyword,
    fetch_html,
    finalize_category_sync,
    make_client,
    now_utc,
    parse_html_list_items,
)
from app.trusted_source_adapters import registry

NRS_BASE = "https://www.nrsis.org.cn"
NRS_FALLBACK = "http://www.nrsis.org.cn/"
NRS_PATHS = ("/", "/std/stdPublicity", "/std/stdQuery", "/portal/std")


class NrsNaturalResourceAdapter(StandardCatalogAdapterMixin):
    adapter_key = "nrs_natural_resource_standard_public"

    config = CategoryConfig(
        "natural_resource_standard",
        "自然资源标准",
        "自然资源部 / 自然资源标准化信息服务平台",
        NRS_BASE,
    )

    def _collect_items(self, client) -> list:
        items = []
        for path in NRS_PATHS:
            for base in (NRS_BASE, NRS_FALLBACK.rstrip("/")):
                url = f"{base.rstrip('/')}{path}"
                try:
                    html = fetch_html(client, url)
                except RuntimeError:
                    continue
                parsed = parse_html_list_items(html, base, resource_type=self.config.category_name)
                if parsed:
                    items.extend(parsed)
        return items

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
        with make_client(referer=NRS_BASE) as client:
            try:
                items = self._collect_items(client)
                stats.pages = 1
                self._persist_items(
                    db,
                    source,
                    category,
                    items,
                    stats,
                    discover_files=options.include_detail,
                    client=client,
                )
                db.commit()
                category.resource_count = len(items)
            except Exception as exc:
                errors = 1
                category.last_sync_error = str(exc)[:500]
        finalize_category_sync(db, category, stats, errors=errors, page_number=1, total_pages=1)
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
        with make_client(referer=NRS_BASE) as client:
            items = self._collect_items(client)
        token = keyword.upper()
        results = []
        for item in items:
            if token not in f"{item.standard_no or ''} {item.title}".upper():
                continue
            results.append(
                build_search_result(
                    source,
                    adapter_key=self.adapter_key,
                    item_id=item.item_id,
                    standard_no=item.standard_no,
                    standard_name=item.title,
                    source_status=item.source_status,
                    detail_url=item.detail_url,
                    query=query,
                )
            )
        return results[:20]


registry.register(NrsNaturalResourceAdapter())
