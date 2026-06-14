"""交通运输部交通运输标准化信息系统 adapter."""

from __future__ import annotations

import re
from urllib.parse import urlencode

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
)
from app.trusted_source_adapters import registry

MOT_BASE = "https://jtst.mot.gov.cn"
MOT_STD_PAGE = f"{MOT_BASE}/search/std"
MOT_STD_ROW_PATTERN = re.compile(r"(?:GB/T|JT/T|JTG|JJG(?:\(\s*交通\s*\))?|JT\s*/?\s*T)\s*[\d./-]+", re.I)
MOT_EXCLUDED_TIDS = frozenset({"BV_JJG_JT_PLAN", "BV_GBF_PROJECT"})
MOT_LIST_STREAMS: tuple[dict[str, str], ...] = (
    {"tid": "gb", "q": ""},
    {"tid": "jjg", "q": ""},
)


def build_mot_detail_url(tid: str | None, pid: str | None) -> str | None:
    if not pid:
        return None
    tid = (tid or "").strip()
    if tid == "BV_HB":
        return f"{MOT_BASE}/hb/search/stdHBDetailed?id={pid}"
    if tid == "BV_GBF_INFO":
        return f"{MOT_BASE}/gfs/search/gfsDetailed?id={pid}"
    return f"{MOT_BASE}/gb/search/gbDetailed?id={pid}"


def extract_mot_standard_no(title: str) -> str | None:
    standard_no = extract_standard_no_from_title(title)
    if standard_no:
        return standard_no
    match = re.search(r"JJG\s*\(\s*交通\s*\)\s*[\d-]+", title, re.I)
    if match:
        return re.sub(r"\s+", " ", match.group(0)).strip()
    match = re.search(r"JJG\s+[\d-]+", title, re.I)
    if match:
        return re.sub(r"\s+", " ", match.group(0)).strip()
    return None


def parse_mot_stdpage_items(html: str, *, resource_type: str, list_tid: str | None = None) -> list[ParsedListItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[ParsedListItem] = []
    seen: set[str] = set()

    def append_item(*, tid: str | None, pid: str | None, title: str, source_status: str | None) -> None:
        title = re.sub(r"\s+", " ", title).strip()
        if not title or not MOT_STD_ROW_PATTERN.search(title):
            return
        if tid in MOT_EXCLUDED_TIDS:
            return
        if any(keyword in title for keyword in ("计划", "征求意见", "公告", "目录")):
            return
        detail_url = build_mot_detail_url(tid, pid)
        item_id = detail_hash({"title": title, "url": detail_url, "tid": tid, "pid": pid})
        if item_id in seen:
            return
        seen.add(item_id)
        items.append(
            ParsedListItem(
                item_id=item_id,
                title=title,
                detail_url=detail_url,
                standard_no=extract_mot_standard_no(title),
                source_status=source_status,
                summary=source_status,
                resource_type=resource_type,
                raw={
                    "title": title,
                    "url": detail_url,
                    "tid": tid,
                    "pid": pid,
                    "list_tid": list_tid,
                    "status": source_status,
                },
            )
        )

    for anchor in soup.select("table a[tid][pid]"):
        row = anchor.find_parent("tr")
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")] if row else []
        source_status = cells[1].strip() if len(cells) > 1 else None
        append_item(
            tid=anchor.get("tid"),
            pid=anchor.get("pid"),
            title=anchor.get_text(" ", strip=True),
            source_status=source_status,
        )

    if items:
        return items

    for row in soup.select("table tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        anchor = row.find("a", href=True)
        title = anchor.get_text(" ", strip=True) if anchor else cells[0]
        append_item(tid=None, pid=None, title=title, source_status=cells[1].strip() if len(cells) > 1 else None)
    return items


class MotTransportAdapter(StandardCatalogAdapterMixin):
    adapter_key = "mot_transport_standard_public"

    config = CategoryConfig(
        "transport_standard",
        "交通运输标准",
        "交通运输部 / 交通运输标准化信息系统",
        MOT_STD_PAGE,
    )

    def _list_page_url(self, *, stream: dict[str, str], page: int) -> str:
        params = {"q": stream["q"], "tid": stream["tid"]}
        if page > 1:
            params["pageNo"] = str(page)
        return f"{MOT_BASE}/search/stdPage?{urlencode(params)}"

    def _fetch_stream_page(self, client, stream: dict[str, str], page: int) -> list[ParsedListItem]:
        url = self._list_page_url(stream=stream, page=page)
        html = fetch_html(client, url)
        return parse_mot_stdpage_items(html, resource_type=self.config.category_name, list_tid=stream["tid"])

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
                page_items: list[ParsedListItem] = []
                for stream in MOT_LIST_STREAMS:
                    try:
                        page_items.extend(self._fetch_stream_page(client, stream, page_number))
                    except Exception as exc:
                        errors += 1
                        category.last_sync_error = str(exc)[:500]
                        break
                if errors:
                    break
                fresh_items = [item for item in page_items if item.item_id not in seen_ids]
                if not fresh_items and page_number > start_page:
                    break
                for item in page_items:
                    seen_ids.add(item.item_id)
                if not fresh_items:
                    continue
                last_page = page_number
                stats.pages += 1
                self._persist_items(
                    db,
                    source,
                    category,
                    fresh_items,
                    stats,
                    discover_files=options.include_detail,
                    client=client,
                )
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
        items: list[ParsedListItem] = []
        with make_client(referer=MOT_STD_PAGE) as client:
            for stream in MOT_LIST_STREAMS:
                stream_query = dict(stream)
                if keyword:
                    stream_query["q"] = keyword
                html = fetch_html(client, self._list_page_url(stream=stream_query, page=1))
                items.extend(
                    parse_mot_stdpage_items(
                        html,
                        resource_type=self.config.category_name,
                        list_tid=stream["tid"],
                    )
                )
        deduped: dict[str, ParsedListItem] = {item.item_id: item for item in items}
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
            for item in list(deduped.values())[:20]
        ]


registry.register(MotTransportAdapter())
