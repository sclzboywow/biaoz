"""工业和信息化部标准信息服务平台 adapter."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app import models
from app.batch2_adapters.base import (
    AnnouncementCatalogAdapterMixin,
    CategoryConfig,
    TrustedSourceSearchQuery,
    TrustedSourceSyncOptions,
    TrustedSourceSyncStats,
    absolute_url,
    date_from_millis,
    delay,
    ensure_single_category,
    fetch_html,
    fetch_json_list,
    finalize_category_sync,
    make_client,
    now_utc,
    paginate_indices,
    parse_html_list_items,
)
from app.trusted_source_adapters import registry

MIIT_BASE = "https://www.miit.gov.cn"
MIIT_STD_PORTAL = "https://std.miit.gov.cn"
MIIT_SEARCH_URL = f"{MIIT_BASE}/search-front-server/api/search/info"
MIIT_SEARCH_QUERIES = ("行业标准", "报批", "标准公告", "征求意见")
MIIT_FALLBACK_URLS = (
    f"{MIIT_BASE}/",
    f"{MIIT_BASE}/zwgk/index.html",
)


class MiitStandardAdapter(AnnouncementCatalogAdapterMixin):
    adapter_key = "miit_standard_public"

    config = CategoryConfig(
        "miit_standard_enhancement",
        "工业和信息化标准增强",
        "工业和信息化部 / 标准信息服务平台",
        MIIT_STD_PORTAL,
    )

    def _classify_announce_type(self, title: str) -> str:
        if "征求意见" in title:
            return "征求意见"
        if any(token in title for token in ("废止", "失效", "作废")):
            return "废止目录"
        if any(token in title for token in ("计划", "目录", "公告", "公示", "报批")):
            return "标准公告"
        return "标准公告"

    def _fetch_search_page(self, client, query: str, page: int) -> list[tuple[str, str | None, date | None]]:
        payload = {
            "websiteid": "110000000000000",
            "pg": 10,
            "p": page,
            "tpl": 14,
            "category": 18,
            "q": query,
        }
        data = fetch_json_list(client, MIIT_SEARCH_URL, method="GET", payload=payload)
        if not isinstance(data, dict):
            return []
        search_result = (data.get("data") or {}).get("searchResult") or {}
        rows = search_result.get("dataResults") or []
        items: list[tuple[str, str | None, date | None]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            record = row.get("data") or {}
            title = str(record.get("title") or record.get("title_text") or "").strip()
            if len(title) < 8:
                continue
            detail_url = absolute_url(MIIT_BASE, record.get("url"))
            publish_date = date_from_millis(record.get("cdate") or record.get("deploytime"))
            items.append((title, detail_url, publish_date))
        return items

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
        seen_titles: set[str] = set()
        last_page = start_page - 1
        with make_client(referer=f"{MIIT_BASE}/search/zcwjk.html") as client:
            try:
                for page_number in paginate_indices(start_page, options.max_pages):
                    query = MIIT_SEARCH_QUERIES[(page_number - 1) % len(MIIT_SEARCH_QUERIES)]
                    search_page = (page_number - 1) // len(MIIT_SEARCH_QUERIES) + 1
                    rows = self._fetch_search_page(client, query, search_page)
                    if not rows and page_number > start_page:
                        break
                    stats.pages += 1
                    last_page = page_number
                    for title, detail_url, publish_date in rows:
                        if title in seen_titles:
                            continue
                        seen_titles.add(title)
                        announce_type = self._classify_announce_type(title)
                        self._upsert_announcement(
                            db,
                            source,
                            category,
                            title=title,
                            detail_url=detail_url,
                            announce_type=announce_type,
                            publish_date=publish_date,
                            summary=title,
                            stats=stats,
                        )
                    db.commit()
                    delay()

                if stats.items == 0:
                    for list_url in MIIT_FALLBACK_URLS[: max(1, options.max_pages)]:
                        html = fetch_html(client, list_url)
                        parsed = parse_html_list_items(html, MIIT_BASE, resource_type="标准公告")
                        stats.pages += 1
                        for item in parsed:
                            if not any(token in item.title for token in ("标准", "征求", "公示", "公告", "报批")):
                                continue
                            if item.title in seen_titles:
                                continue
                            seen_titles.add(item.title)
                            self._upsert_announcement(
                                db,
                                source,
                                category,
                                title=item.title,
                                detail_url=item.detail_url,
                                announce_type=self._classify_announce_type(item.title),
                                publish_date=item.publish_date,
                                summary=item.summary,
                                stats=stats,
                            )
                    db.commit()
                category.resource_count = stats.items
            except Exception as exc:
                errors = 1
                category.last_sync_error = str(exc)[:500]
        finalize_category_sync(db, category, stats, errors=errors, page_number=last_page or 1, total_pages=None)
        return stats

    def _search_external_impl(self, db, source_id, query):
        return []


registry.register(MiitStandardAdapter())
