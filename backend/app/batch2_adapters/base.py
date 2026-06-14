"""Shared utilities and sync mixins for batch-2 trusted source adapters."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from sqlalchemy.orm import Session

from app import models
from app.batch2_admission import is_batch2_trusted_source, sanitize_batch2_resource_updates
from app.batch2_http import absolute_url, fetch_html, make_client
from app.standard_number import extract_all_codes_from_text, normalize_standard_no
from app.status_calibration import attach_change_logs_to_documents, calibrate_resource_status
from app.trusted_source_adapters import (
    TrustedSourceSearchQuery,
    TrustedSourceSearchResult,
    TrustedSourceSyncOptions,
    TrustedSourceSyncStats,
)
from app.trusted_source_search_service import LocalIndexSearchAdapterMixin

BATCH2_REQUEST_DELAY_SECONDS = float(os.getenv("BATCH2_REQUEST_DELAY_SECONDS", "0.8"))
BATCH2_RETRY_ATTEMPTS = int(os.getenv("BATCH2_RETRY_ATTEMPTS", "3"))
MONITORED_CHANGE_FIELDS = {
    "standard_no",
    "standard_name",
    "source_status",
    "publish_date",
    "effective_date",
    "abolish_date",
    "summary",
    "change_info",
    "pdf_trial_url",
    "resource_type",
}


@dataclass(frozen=True)
class CategoryConfig:
    category_id: str
    category_name: str
    category_path: str
    source_url: str


def now_utc() -> datetime:
    return datetime.now(UTC)


def delay(seconds: float = BATCH2_REQUEST_DELAY_SECONDS) -> None:
    if seconds > 0:
        time.sleep(seconds)


def text(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    return raw or None


def limit_text(value: str | None, max_length: int) -> str | None:
    if value is None or len(value) <= max_length:
        return value
    return value[:max_length]


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    match = re.search(r"(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})", raw)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def date_from_millis(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).date()
    except (TypeError, ValueError, OSError):
        return None


def detail_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def system_status(source_status: str | None) -> str:
    if source_status and ("废止" in source_status or "失效" in source_status):
        return "来源确认废止"
    if source_status and ("现行" in source_status or "公布" in source_status or "有效" in source_status):
        return "来源确认现行"
    return "待复核"


def default_headers(referer: str | None = None) -> dict[str, str]:
    from app.batch2_http import default_headers as _default_headers

    return _default_headers(referer)


def make_client(referer: str | None = None, timeout: float = 30) -> httpx.Client:
    from app.batch2_http import make_client as _make_client

    return _make_client(referer, timeout)


def ensure_single_category(db: Session, source: models.TrustedSource, config: CategoryConfig) -> models.SourceCategory:
    category = (
        db.query(models.SourceCategory)
        .filter(
            models.SourceCategory.source_id == source.id,
            models.SourceCategory.source_category_id == config.category_id,
        )
        .first()
    )
    if category is None:
        category = models.SourceCategory(
            source_id=source.id,
            source_category_id=config.category_id,
            category_name=config.category_name,
            category_path=config.category_path,
            source_url=config.source_url,
            sync_status="待同步",
        )
        db.add(category)
        db.flush()
    else:
        category.category_name = config.category_name
        category.category_path = config.category_path
        category.source_url = config.source_url
    return category


def record_change(db: Session, resource: models.StandardResource, field_name: str, old_value: Any, new_value: Any) -> None:
    if field_name not in MONITORED_CHANGE_FIELDS:
        return
    old_text = "" if old_value is None else str(old_value)
    new_text = "" if new_value is None else str(new_value)
    if old_text == new_text:
        return
    exists = (
        db.query(models.StandardChangeLog)
        .filter(
            models.StandardChangeLog.standard_resource_id == resource.id,
            models.StandardChangeLog.field_name == field_name,
            models.StandardChangeLog.old_value == old_text,
            models.StandardChangeLog.new_value == new_text,
        )
        .first()
    )
    if exists:
        return
    db.add(
        models.StandardChangeLog(
            standard_resource_id=resource.id,
            field_name=field_name,
            old_value=old_text,
            new_value=new_text,
            change_type="字段变化",
            source_url=resource.detail_url,
            handled_status="已处理",
            evidence_summary=f"可信源字段 {field_name} 发生变化",
        )
    )


def upsert_resource(
    db: Session,
    source: models.TrustedSource,
    item_id: str,
    updates: dict[str, Any],
    *,
    evidence_summary: str | None = None,
) -> tuple[models.StandardResource, bool]:
    if is_batch2_trusted_source(source):
        updates = sanitize_batch2_resource_updates(updates)
    resource = (
        db.query(models.StandardResource)
        .filter(models.StandardResource.source_id == source.id, models.StandardResource.source_book_id == item_id)
        .first()
    )
    created = resource is None
    if resource is None:
        resource = models.StandardResource(
            source_id=source.id,
            source_book_id=item_id,
            source_name=source.source_name,
            standard_name=updates.get("standard_name") or item_id,
        )
        db.add(resource)
        db.flush()

    standard_no = updates.get("standard_no") or resource.standard_no
    number_parts = normalize_standard_no(standard_no)
    updates.update(
        {
            "raw_standard_no": number_parts.raw,
            "normalized_standard_no": number_parts.normalized,
            "standard_prefix": number_parts.prefix,
            "standard_main_no": number_parts.main_no,
            "standard_year": number_parts.year,
            "standard_revision_note": number_parts.revision_note,
            "source_confidence": source.trust_score,
            "last_synced_at": now_utc(),
            "sync_status": "已同步",
        }
    )
    for field_name, value in updates.items():
        if not created:
            record_change(db, resource, field_name, getattr(resource, field_name), value)
        setattr(resource, field_name, value)

    detail_hash_value = updates.get("detail_hash")
    if detail_hash_value:
        detail = (
            db.query(models.StandardDetail)
            .filter(models.StandardDetail.standard_resource_id == resource.id)
            .first()
        )
        if detail is None:
            detail = models.StandardDetail(standard_resource_id=resource.id)
            db.add(detail)
        detail.catalog_text = evidence_summary
        evidence_exists = (
            db.query(models.StandardEvidence)
            .filter(
                models.StandardEvidence.standard_resource_id == resource.id,
                models.StandardEvidence.page_html_hash == detail_hash_value,
            )
            .first()
        )
        if evidence_exists is None:
            db.add(
                models.StandardEvidence(
                    standard_resource_id=resource.id,
                    source_name=source.source_name,
                    source_level=source.trust_level,
                    source_url=resource.detail_url,
                    raw_status_text=resource.source_status,
                    parsed_status=resource.system_status,
                    page_summary=evidence_summary or resource.summary,
                    page_html_hash=detail_hash_value,
                    evidence_note="第二批可信源列表入库",
                )
            )
    return resource, created


def finalize_category_sync(
    db: Session,
    category: models.SourceCategory,
    stats: TrustedSourceSyncStats,
    *,
    errors: int,
    page_number: int,
    total_pages: int | None = None,
) -> None:
    category.last_sync_finished_at = now_utc()
    category.last_synced_at = category.last_sync_finished_at
    category.last_synced_page = page_number
    if errors:
        category.sync_status = "同步失败"
    elif total_pages and page_number >= total_pages:
        category.sync_status = "已同步"
    else:
        category.sync_status = "待同步"
    stats.errors = errors
    db.commit()


def apply_resource_calibration(db: Session, resource: models.StandardResource, stats: TrustedSourceSyncStats) -> None:
    calibration = calibrate_resource_status(db, resource)
    stats.matches += calibration["matches"]
    stats.sync_logs += calibration["sync_logs"]
    stats.alerts += calibration["alerts"]
    stats.linked_change_logs += attach_change_logs_to_documents(db, resource)


def external_search_keyword(query: TrustedSourceSearchQuery) -> str | None:
    parts = normalize_standard_no(query.normalized_standard_no or query.standard_no)
    if parts.main_no and parts.year:
        return f"{parts.main_no}-{parts.year}"
    if parts.main_no:
        return parts.main_no
    if query.standard_no:
        return query.standard_no.strip()[:80]
    for keyword in query.keywords:
        token = keyword.strip()
        if token:
            return token[:80]
    if query.standard_name:
        return query.standard_name.strip()[:80]
    return None


def score_external_match(
    *,
    query: TrustedSourceSearchQuery,
    standard_no: str | None,
    standard_name: str | None,
) -> tuple[int, str]:
    number_parts = normalize_standard_no(standard_no)
    title_score = int(SequenceMatcher(None, query.standard_name or "", standard_name or "").ratio() * 100)
    number_match = bool(
        query.normalized_standard_no
        and number_parts.normalized
        and query.normalized_standard_no == number_parts.normalized
    ) or bool(query.standard_no and standard_no and query.standard_no == standard_no)
    for keyword in query.keywords:
        token = keyword.strip().upper()
        if token and standard_no and token in standard_no.upper():
            number_match = True
            break
    if number_match and title_score >= 80:
        return 95, "外网实时命中：编号与标题高度一致"
    if number_match:
        return 90, "外网实时命中：标准编号一致"
    if title_score >= 80:
        return 80, f"外网实时命中：标题相似度 {title_score}%"
    return max(55, title_score), f"外网实时命中：标题相似度 {title_score}%"


def build_search_result(
    source: models.TrustedSource,
    *,
    adapter_key: str,
    item_id: str,
    standard_no: str | None,
    standard_name: str,
    source_status: str | None,
    detail_url: str | None,
    publish_date: date | None = None,
    effective_date: date | None = None,
    query: TrustedSourceSearchQuery | None = None,
) -> TrustedSourceSearchResult:
    number_parts = normalize_standard_no(standard_no)
    score, reason = (90, "本地索引命中") if query is None else score_external_match(
        query=query, standard_no=standard_no, standard_name=standard_name
    )
    return TrustedSourceSearchResult(
        source_id=source.id,
        source_name=source.source_name or "",
        standard_no=standard_no,
        normalized_standard_no=number_parts.normalized,
        standard_name=standard_name,
        source_status=source_status,
        publish_date=publish_date,
        effective_date=effective_date,
        detail_url=detail_url,
        confidence_score=score,
        match_reason=reason,
        raw={"adapter_key": adapter_key, "external_item_id": item_id},
    )


def extract_standard_no_from_title(title: str) -> str | None:
    numbers = extract_all_codes_from_text(title)
    return numbers[0] if numbers else None


def absolute_url(base_url: str, href: str | None) -> str | None:
    from app.batch2_http import absolute_url as _absolute_url

    return _absolute_url(base_url, href)


def host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).netloc or None


@dataclass
class ParsedListItem:
    item_id: str
    title: str
    detail_url: str | None = None
    standard_no: str | None = None
    source_status: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    summary: str | None = None
    resource_type: str | None = None
    raw: dict | None = None


def parse_html_list_items(html: str, base_url: str, *, resource_type: str) -> list[ParsedListItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[ParsedListItem] = []
    seen: set[str] = set()

    def add_item(title: str, href: str | None, extra: str | None = None) -> None:
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 4:
            return
        detail_url = absolute_url(base_url, href)
        item_id = detail_hash({"title": title, "url": detail_url})
        if item_id in seen:
            return
        seen.add(item_id)
        standard_no = extract_standard_no_from_title(title)
        summary = extra
        items.append(
            ParsedListItem(
                item_id=item_id,
                title=title,
                detail_url=detail_url,
                standard_no=standard_no,
                summary=summary,
                resource_type=resource_type,
                raw={"title": title, "url": detail_url},
            )
        )

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            anchor = row.find("a", href=True)
            title = anchor.get_text(" ", strip=True) if anchor else cells[0].get_text(" ", strip=True)
            href = anchor["href"] if anchor else None
            extra = " | ".join(cell.get_text(" ", strip=True) for cell in cells[1:3])
            add_item(title, href, extra)

    for anchor in soup.select("ul li a[href], .list a[href], .news_list a[href], .xxgk_list a[href]"):
        add_item(anchor.get_text(" ", strip=True), anchor.get("href"))

    if not items:
        for anchor in soup.find_all("a", href=True):
            title = anchor.get_text(" ", strip=True)
            href = anchor.get("href")
            if not title or len(title) < 8:
                continue
            if any(token in title for token in ("首页", "更多", "登录", "注册", "English")):
                continue
            if href and not href.startswith("#") and not href.lower().startswith("javascript"):
                add_item(title, href)
    return items


def parse_json_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("records", "rows", "data", "list", "result", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            for nested in ("records", "rows", "list", "items"):
                nested_value = value.get(nested)
                if isinstance(nested_value, list):
                    return [row for row in nested_value if isinstance(row, dict)]
    return []


def json_record_to_item(row: dict[str, Any], base_url: str, *, resource_type: str) -> ParsedListItem | None:
    item_id = text(row.get("pk") or row.get("id") or row.get("stdId") or row.get("standardId") or row.get("code"))
    standard_no = text(row.get("code") or row.get("standardNo") or row.get("stdNo") or row.get("standard_no"))
    title = text(row.get("chName") or row.get("name") or row.get("title") or row.get("standardName")) or standard_no
    if not item_id and not standard_no and not title:
        return None
    if not item_id:
        item_id = detail_hash(row)
    detail_path = text(row.get("detailUrl") or row.get("url"))
    detail_url = absolute_url(base_url, detail_path) if detail_path else None
    if not detail_url and item_id and not str(item_id).startswith("http"):
        detail_url = f"{base_url.rstrip('/')}/detail/{item_id}"
    source_status = text(row.get("status") or row.get("stdStatus") or row.get("state"))
    return ParsedListItem(
        item_id=str(item_id),
        title=title or str(item_id),
        detail_url=detail_url,
        standard_no=standard_no or extract_standard_no_from_title(title or ""),
        source_status=source_status,
        publish_date=date_from_millis(row.get("issueDate") or row.get("publishDate")) or parse_date(row.get("publishDate")),
        effective_date=date_from_millis(row.get("actDate") or row.get("effectiveDate")) or parse_date(row.get("effectiveDate")),
        summary=text(row.get("summary") or row.get("remark")),
        resource_type=resource_type,
        raw=row,
    )


class StandardCatalogAdapterMixin(LocalIndexSearchAdapterMixin):
    """Read-only standard catalog sync for batch-2 sources."""

    def _persist_items(
        self,
        db: Session,
        source: models.TrustedSource,
        category: models.SourceCategory,
        items: list[ParsedListItem],
        stats: TrustedSourceSyncStats,
        *,
        discover_files: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        for item in items:
            payload = {
                "standard_no": item.standard_no,
                "source_status_raw": item.source_status,
                "standard_name": item.title,
                "resource_type": item.resource_type or category.category_name,
                "source_status": item.source_status,
                "system_status": system_status(item.source_status),
                "publish_date": item.publish_date,
                "effective_date": item.effective_date,
                "summary": item.summary,
                "source_category_path": category.category_path,
                "detail_url": item.detail_url,
                "detail_hash": detail_hash(item.raw or {"title": item.title, "url": item.detail_url}),
            }
            resource, created = upsert_resource(db, source, item.item_id, payload, evidence_summary=item.summary)
            stats.created += 1 if created else 0
            stats.updated += 0 if created else 1
            stats.items += 1
            if is_batch2_trusted_source(source):
                from app.batch2_file_ingest_service import apply_batch2_resource_file_status

                apply_batch2_resource_file_status(
                    db,
                    source,
                    resource,
                    discover_files=discover_files,
                    client=client,
                )
            else:
                apply_resource_calibration(db, resource, stats)

    def search_external(self, db: Session, source_id: int, query: TrustedSourceSearchQuery) -> list[TrustedSourceSearchResult]:
        return self._search_external_impl(db, source_id, query)


class AnnouncementCatalogAdapterMixin(StandardCatalogAdapterMixin):
    """Announcement/plan/comment-period entries; standard_no may be empty."""

    announcement_resource_type: str = "标准公告"

    def _announcement_item_id(self, title: str, detail_url: str | None, announce_type: str) -> str:
        return detail_hash({"title": title, "url": detail_url, "type": announce_type})

    def _upsert_announcement(
        self,
        db: Session,
        source: models.TrustedSource,
        category: models.SourceCategory,
        *,
        title: str,
        detail_url: str | None,
        announce_type: str,
        publish_date: date | None = None,
        summary: str | None = None,
        stats: TrustedSourceSyncStats,
    ) -> None:
        standard_no = extract_standard_no_from_title(title)
        item_id = self._announcement_item_id(title, detail_url, announce_type)
        if standard_no:
            existing = (
                db.query(models.StandardResource)
                .filter(
                    models.StandardResource.source_id == source.id,
                    models.StandardResource.normalized_standard_no == normalize_standard_no(standard_no).normalized,
                    models.StandardResource.resource_type == announce_type,
                )
                .first()
            )
            if existing and existing.source_book_id != item_id:
                item_id = existing.source_book_id or item_id
        payload = {
            "standard_no": standard_no,
            "standard_name": title,
            "resource_type": announce_type,
            "source_status": announce_type,
            "system_status": "待复核",
            "publish_date": publish_date,
            "summary": summary or title,
            "change_info": summary,
            "source_category_path": category.category_path,
            "detail_url": detail_url,
            "detail_hash": detail_hash({"title": title, "url": detail_url, "type": announce_type}),
        }
        resource, created = upsert_resource(db, source, item_id, payload, evidence_summary=summary)
        stats.created += 1 if created else 0
        stats.updated += 0 if created else 1
        stats.items += 1
        if is_batch2_trusted_source(source):
            from app.batch2_file_ingest_service import apply_batch2_resource_file_status

            apply_batch2_resource_file_status(db, source, resource, discover_files=False)
        else:
            apply_resource_calibration(db, resource, stats)


def fetch_json_list(
    client: httpx.Client,
    url: str,
    *,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    last_error: Exception | None = None
    for attempt in range(1, BATCH2_RETRY_ATTEMPTS + 1):
        try:
            if method.upper() == "GET":
                response = client.get(url, params=payload or data)
            else:
                if payload is not None:
                    response = client.post(url, json=payload)
                else:
                    response = client.post(url, data=data or {})
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt < BATCH2_RETRY_ATTEMPTS:
                time.sleep(min(2 * attempt, 8))
    raise RuntimeError(f"fetch failed for {url}: {last_error}")


def fetch_html(client: httpx.Client, url: str) -> str:
    from app.batch2_http import fetch_html as _fetch_html

    return _fetch_html(client, url)


def paginate_indices(start_page: int, max_pages: int) -> range:
    return range(start_page, start_page + max(1, max_pages))
