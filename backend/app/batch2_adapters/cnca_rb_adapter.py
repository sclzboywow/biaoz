"""认证认可标准化信息服务平台 RB/T adapter."""

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
    delay,
    ensure_single_category,
    external_search_keyword,
    fetch_html,
    fetch_json_list,
    finalize_category_sync,
    json_record_to_item,
    make_client,
    now_utc,
    paginate_indices,
    parse_html_list_items,
    parse_json_records,
)
from app.trusted_source_adapters import registry

CNCA_RB_BASE = "https://rbtest.cnca.cn"
CNCA_RB_LIST = f"{CNCA_RB_BASE}/portal/xxcx/std"
CNCA_RB_API_CANDIDATES = (
    f"{CNCA_RB_BASE}/portal/xxcx/std/list",
    f"{CNCA_RB_BASE}/portal/xxcx/std/query",
    f"{CNCA_RB_BASE}/portal/xxcx/std/page",
)


class CncaRbStandardAdapter(StandardCatalogAdapterMixin):
    adapter_key = "cnca_rb_standard_public"

    config = CategoryConfig(
        "cnca_rb_standard",
        "认证认可标准",
        "认证认可标准化信息服务平台 / RB/T",
        CNCA_RB_LIST,
    )

    def _fetch_page(self, client, page: int) -> list:
        for url in CNCA_RB_API_CANDIDATES:
            try:
                data = fetch_json_list(
                    client,
                    url,
                    method="POST",
                    payload={"pageNum": page, "pageSize": 50, "current": page, "size": 50},
                )
                rows = parse_json_records(data)
                items = [
                    item
                    for row in rows
                    if (item := json_record_to_item(row, CNCA_RB_BASE, resource_type=self.config.category_name)) is not None
                ]
                if items:
                    return items
            except RuntimeError:
                continue
        html = fetch_html(client, CNCA_RB_LIST)
        return parse_html_list_items(html, CNCA_RB_BASE, resource_type=self.config.category_name)

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
        with make_client(referer=CNCA_RB_LIST) as client:
            for page_number in paginate_indices(start_page, options.max_pages):
                try:
                    items = self._fetch_page(client, page_number)
                except Exception as exc:
                    errors += 1
                    category.last_sync_error = str(exc)[:500]
                    break
                if not items:
                    break
                last_page = page_number
                stats.pages += 1
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
                delay()
        finalize_category_sync(db, category, stats, errors=errors, page_number=max(last_page, 1), total_pages=None)
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
        with make_client(referer=CNCA_RB_LIST) as client:
            items = self._fetch_page(client, 1)
        results = []
        token = keyword.upper()
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


registry.register(CncaRbStandardAdapter())
