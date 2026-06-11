from __future__ import annotations

import hashlib
import html as ihtml
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app import models
from app.standard_number import normalize_standard_no
from app.status_calibration import CHANGE_FIELD_LABELS, attach_change_logs_to_documents, calibrate_resource_status
from app.trusted_source_adapters import (
    TrustedSourceAdapter,
    TrustedSourceSearchQuery,
    TrustedSourceSearchResult,
    TrustedSourceSyncOptions,
    TrustedSourceSyncStats,
    registry,
)
from app.trusted_source_search_service import LocalIndexSearchAdapterMixin

BASE_URL = "https://ebook.chinabuilding.com.cn"

MONITORED_CHANGE_FIELDS = {
    "standard_no",
    "standard_name",
    "source_status",
    "publish_date",
    "effective_date",
    "abolish_date",
    "change_info",
}


@dataclass(frozen=True)
class SublibConfig:
    sublib_id: int
    category_name: str
    category_path: str
    total_pages_hint: int


SUBLIBS = [
    SublibConfig(2118, "国标图集", "标准图集 / 国标图集", 82),
    SublibConfig(2246, "国家标准", "标准规范 / 工程建设标准规范 / 工程建设国家标准", 349),
    SublibConfig(2398, "行业标准", "标准规范 / 工程建设标准规范 / 工程建设行业标准", 1867),
    SublibConfig(2441, "地方标准", "标准规范 / 工程建设标准规范 / 工程建设地方标准", 28),
    SublibConfig(2481, "政策法规与技术文件", "政策法规 / 技术文件", 82),
]


def _fallback_pages_hint(category: models.SourceCategory | None) -> int:
    if category and category.resource_count:
        return max(1, (category.resource_count + 19) // 20)
    return 1


def _sublibs_from_categories(
    db: Session,
    source: models.TrustedSource,
    sublib_id: int | None,
    only_pending: bool = False,
    limit: int | None = None,
) -> list[SublibConfig]:
    query = db.query(models.SourceCategory).filter(models.SourceCategory.source_id == source.id)
    if sublib_id is not None:
        query = query.filter(models.SourceCategory.source_category_id == str(sublib_id))
    if only_pending:
        query = query.filter(
            (models.SourceCategory.sync_status.is_(None))
            | (models.SourceCategory.sync_status.in_(["待同步", "同步失败"]))
        )
    query = query.order_by(models.SourceCategory.source_category_id)
    if limit:
        query = query.limit(limit)
    categories = list(query)
    return [
        SublibConfig(
            int(category.source_category_id),
            category.category_name,
            category.category_path or category.category_name,
            _fallback_pages_hint(category),
        )
        for category in categories
        if category.source_category_id and category.source_category_id.isdigit()
    ]


def _category_for_sublib(db: Session, source: models.TrustedSource, sublib_id: int) -> models.SourceCategory | None:
    return (
        db.query(models.SourceCategory)
        .filter(
            models.SourceCategory.source_id == source.id,
            models.SourceCategory.source_category_id == str(sublib_id),
        )
        .first()
    )


def _book_ids_hash(items: list[dict[str, str]]) -> str:
    value = ",".join(sorted(item["book_id"] for item in items if item.get("book_id")))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _client(timeout_seconds: int = 20) -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=timeout_seconds,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        },
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"(\d{4})[-/.年](\d{1,2})(?:[-/.月](\d{1,2}))?", value)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3) or 1)
    return date(year, month, day)


def _strip_html(value: str) -> str:
    return ihtml.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def parse_title(full_title: str) -> tuple[str | None, str]:
    match = re.match(r"^\s*([^:：]+)\s*[:：]\s*(.+)$", full_title.strip())
    if not match:
        return None, full_title.strip()
    return match.group(1).strip(), match.group(2).strip()


def parse_list_items(html: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    pattern = re.compile(
        r'<div class="img-search-list[\s\S]*?<h4 class="search-tit[\s\S]*?'
        r'<a[^>]+href="([^"]*bookID=(\d+)[^"]*)"[^>]*>([\s\S]*?)</a>[\s\S]*?'
        r'<span class="(active|abolish)">([\s\S]*?)</span>',
        re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        href = ihtml.unescape(match.group(1))
        book_id = match.group(2)
        full_title = _strip_html(match.group(3))
        status_text = _strip_html(match.group(5))
        standard_no, title = parse_title(full_title)
        detail_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        items.append(
            {
                "book_id": book_id,
                "standard_no": standard_no or "",
                "title": title,
                "status": status_text,
                "detail_url": detail_url,
            }
        )
    return items


def _pick_date(label: str, html: str) -> date | None:
    match = re.search(label + r"[^0-9]*(\d{4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2})?)", html)
    return _parse_date(match.group(1)) if match else None


def _extract_label_value(labels: list[str], html: str, maxlen: int = 300) -> str | None:
    for label in labels:
        patterns = [
            re.compile(
                label + r"\s*[:：]?\s*(?:</?[a-zA-Z0-9]+[^>]*>)*\s*([^<\r\n]{1," + str(maxlen) + r"})",
                re.IGNORECASE,
            ),
            re.compile(label + r"[\s\S]{0,80}?<[^>]*>\s*([^<]{1," + str(maxlen) + r"})\s*</", re.IGNORECASE),
        ]
        for pattern in patterns:
            match = pattern.search(html)
            if match:
                value = ihtml.unescape(match.group(1)).strip()
                if value and value not in {"：", ":"}:
                    return value
    return None


def _valid_resource_type(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if re.search(r"(发布|出版|实施|废止|入库)?日期\s*[:：]?\s*\d{4}", cleaned):
        return None
    if re.search(r"\d{4}[-/.年]\d{1,2}", cleaned):
        return None
    return cleaned


def _extract_section(html: str, labels: list[str], max_chars: int = 5000) -> str | None:
    for label in labels:
        match = re.search(label + r"[\s\S]{0,120}?(<div[\s\S]{0," + str(max_chars) + r"}?</div>)", html)
        if match:
            text = _strip_html(match.group(1))
            if text:
                return text[:max_chars]
    return None


def _resolve_pdf_file_url(client: httpx.Client, book_id: str) -> str:
    reader_url = f"{BASE_URL}/zbooklib/bookpdf/probation?SiteID=1&bookID={book_id}"
    try:
        response = client.get(reader_url)
        response.raise_for_status()
    except httpx.HTTPError:
        return reader_url

    html = response.text
    prefix_match = re.search(r'absolute_path_prefix="([^"]+)"', html)
    if not prefix_match:
        return reader_url

    prefix = prefix_match.group(1)
    candidates: list[str] = []
    for href in re.findall(r'href="([^"]+\.css)"', html, flags=re.IGNORECASE):
        name = href.rsplit("/", 1)[-1]
        if name in {"base.min.css", "fancy.min.css"}:
            continue
        candidates.append(prefix + name[:-4] + ".pdf")

    for url in candidates:
        try:
            pdf_response = client.get(url, headers={"Range": "bytes=0-31"})
        except httpx.HTTPError:
            continue
        content_type = (pdf_response.headers.get("content-type") or "").lower()
        if pdf_response.status_code in {200, 206} and "pdf" in content_type and pdf_response.content.startswith(b"%PDF"):
            return url

    return reader_url


def fetch_detail(client: httpx.Client, book_id: str) -> dict[str, Any]:
    detail_url = f"{BASE_URL}/zbooklib/book/detail/show?SiteID=1&bookID={book_id}"
    response = client.get(detail_url)
    response.raise_for_status()
    html = response.text
    detail_hash = hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()

    cover_match = re.search(r"var\s+sharePic\s*=\s*'([^']+)'", html)
    pdf_trial_url = _resolve_pdf_file_url(client, book_id)

    return {
        "detail_url": detail_url,
        "detail_hash": detail_hash,
        "cover": cover_match.group(1) if cover_match else None,
        "publish_date": _pick_date("发布", html) or _pick_date("出版", html),
        "effective_date": _pick_date("实施", html) or _pick_date("生效", html),
        "abolish_date": _pick_date("废止", html),
        "storage_date": _pick_date("入库", html),
        "chief_editor_unit": _extract_label_value(["主编单位", "起草单位", "编制单位", "参编单位"], html, 500),
        "resource_type": _valid_resource_type(_extract_label_value(["资源类型", "标准类型", "图书类型"], html, 120)),
        "summary": _extract_section(html, ["简介", "内容简介"]),
        "catalog_text": _extract_section(html, ["目录"]),
        "mandatory_provisions": _extract_section(html, ["强制性条文", "强条"]),
        "expert_interpretation": _extract_section(html, ["专家解读"]),
        "product_info": _extract_section(html, ["产品信息"]),
        "change_info": _extract_section(html, ["变更信息", "变更"]),
        "related_books": _extract_section(html, ["相关阅读", "相关资源"]),
        "pdf_trial_url": pdf_trial_url,
    }


def _record_change(
    db: Session,
    resource: models.StandardResource,
    field_name: str,
    old_value: Any,
    new_value: Any,
) -> None:
    if field_name not in MONITORED_CHANGE_FIELDS:
        return
    old_text = "" if old_value is None else str(old_value)
    new_text = "" if new_value is None else str(new_value)
    if old_text == new_text:
        return
    existing = (
        db.query(models.StandardChangeLog)
        .filter(
            models.StandardChangeLog.standard_resource_id == resource.id,
            models.StandardChangeLog.field_name == field_name,
            models.StandardChangeLog.old_value == old_text,
            models.StandardChangeLog.new_value == new_text,
        )
        .first()
    )
    if existing:
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
            evidence_summary=f"可信源{CHANGE_FIELD_LABELS.get(field_name, field_name)}发生变化",
        )
    )


def _extract_relation_candidates(text: str | None) -> list[str]:
    if not text:
        return []
    pattern = re.compile(
        r"(?:GB/T|GB|JGJ/T|JGJ|CJJ/T|CJJ|CECS|DB\d{0,2}/T|DB\d{0,2}|T/[A-Z0-9]+|[A-Z]{2,8}/T|[A-Z]{2,8})"
        r"\s*[A-Z]?\d+[A-Z0-9./-]*(?:\s*[-\u2010-\u2015\uff0d]\s*\d{4})?",
        re.IGNORECASE,
    )
    values: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(text):
        normalized = normalize_standard_no(match.group(0)).normalized
        if normalized and normalized not in seen:
            seen.add(normalized)
            values.append(normalized)
    return values


def _relation_type(text: str) -> str:
    if "局部修订" in text:
        return "局部修订"
    if "被" in text and "替代" in text:
        return "被替代"
    if "替代" in text or "代替" in text:
        return "替代"
    return "相关"


def _upsert_relations(db: Session, resource: models.StandardResource, detail: dict[str, Any]) -> None:
    current_no = resource.normalized_standard_no or normalize_standard_no(resource.standard_no).normalized
    if not current_no:
        return
    text = "\n".join(
        value
        for value in [
            detail.get("change_info"),
            detail.get("related_books"),
            detail.get("summary"),
        ]
        if value
    )
    if not text:
        return
    relation_type = _relation_type(text)
    for related_no in _extract_relation_candidates(text):
        if related_no == current_no:
            continue
        existing = (
            db.query(models.StandardRelation)
            .filter(
                models.StandardRelation.current_standard_no == current_no,
                models.StandardRelation.related_standard_no == related_no,
                models.StandardRelation.relation_type == relation_type,
                models.StandardRelation.source_url == resource.detail_url,
            )
            .first()
        )
        if existing:
            continue
        db.add(
            models.StandardRelation(
                current_standard_resource_id=resource.id,
                current_standard_no=current_no,
                related_standard_no=related_no,
                relation_type=relation_type,
                relation_text=text[:1000],
                source_url=resource.detail_url,
                is_manual_confirmed=False,
            )
        )


def _upsert_resource(
    db: Session,
    source: models.TrustedSource,
    sublib: SublibConfig,
    item: dict[str, str],
    detail: dict[str, Any] | None,
) -> tuple[models.StandardResource, bool]:
    resource = (
        db.query(models.StandardResource)
        .filter(
            models.StandardResource.source_id == source.id,
            models.StandardResource.source_book_id == item["book_id"],
        )
        .first()
    )
    created = resource is None
    if resource is None:
        resource = models.StandardResource(
            source_id=source.id,
            source_book_id=item["book_id"],
            source_name=source.source_name,
            standard_name=item["title"],
        )
        db.add(resource)
        db.flush()

    standard_no = item.get("standard_no") or resource.standard_no
    number_parts = normalize_standard_no(standard_no)
    updates = {
        "standard_no": standard_no,
        "raw_standard_no": number_parts.raw,
        "normalized_standard_no": number_parts.normalized,
        "standard_prefix": number_parts.prefix,
        "standard_main_no": number_parts.main_no,
        "standard_year": number_parts.year,
        "standard_revision_note": number_parts.revision_note,
        "source_status_raw": item.get("status"),
        "standard_name": item["title"],
        "source_status": item.get("status"),
        "system_status": "来源确认废止" if item.get("status") == "废止" else "来源确认现行",
        "source_category_path": sublib.category_path,
        "detail_url": item.get("detail_url"),
        "source_confidence": source.trust_score,
        "last_synced_at": datetime.now(UTC),
        "sync_status": "已同步",
    }
    if detail:
        updates.update(
            {
                "resource_type": _valid_resource_type(detail.get("resource_type")) or sublib.category_name,
                "publish_date": detail.get("publish_date"),
                "effective_date": detail.get("effective_date"),
                "abolish_date": detail.get("abolish_date"),
                "storage_date": detail.get("storage_date"),
                "chief_editor_unit": detail.get("chief_editor_unit"),
                "summary": detail.get("summary"),
                "detail_hash": detail.get("detail_hash"),
                "pdf_trial_url": detail.get("pdf_trial_url"),
            }
        )
    else:
        updates["resource_type"] = sublib.category_name

    for field_name, value in updates.items():
        if not created:
            _record_change(db, resource, field_name, getattr(resource, field_name), value)
        setattr(resource, field_name, value)

    if detail:
        existing_detail = (
            db.query(models.StandardDetail)
            .filter(models.StandardDetail.standard_resource_id == resource.id)
            .first()
        )
        if existing_detail is None:
            existing_detail = models.StandardDetail(standard_resource_id=resource.id)
            db.add(existing_detail)
        for field_name in [
            "catalog_text",
            "mandatory_provisions",
            "expert_interpretation",
            "product_info",
            "change_info",
            "related_books",
        ]:
            setattr(existing_detail, field_name, detail.get(field_name))

        evidence_exists = (
            db.query(models.StandardEvidence)
            .filter(
                models.StandardEvidence.standard_resource_id == resource.id,
                models.StandardEvidence.page_html_hash == detail.get("detail_hash"),
                models.StandardEvidence.raw_status_text == resource.source_status,
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
                    page_summary=resource.summary,
                    page_html_hash=resource.detail_hash,
                    evidence_note=f"{source.source_name} 详情页状态证据，可信等级 {source.trust_level}",
                )
            )
        _upsert_relations(db, resource, detail)

    return resource, created


def ensure_source_categories(db: Session, source: models.TrustedSource) -> None:
    for sublib in SUBLIBS:
        existing = (
            db.query(models.SourceCategory)
            .filter(
                models.SourceCategory.source_id == source.id,
                models.SourceCategory.source_category_id == str(sublib.sublib_id),
            )
            .first()
        )
        if existing:
            continue
        db.add(
            models.SourceCategory(
                source_id=source.id,
                source_category_id=str(sublib.sublib_id),
                category_name=sublib.category_name,
                category_path=sublib.category_path,
                source_url=f"{BASE_URL}/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView&sublibID={sublib.sublib_id}",
            )
        )
    db.commit()


def sync_guobiao_resources(
    db: Session,
    max_pages_per_sublib: int = 1,
    include_detail: bool = True,
    sublib_id: int | None = None,
    only_pending_categories: bool = False,
    category_limit: int | None = None,
) -> dict[str, int]:
    source = db.query(models.TrustedSource).filter(models.TrustedSource.source_name == "国标电子书库").first()
    if source is None:
        raise ValueError("国标电子书库可信源不存在")
    ensure_source_categories(db, source)

    selected = _sublibs_from_categories(db, source, sublib_id, only_pending_categories, category_limit)
    if not selected and not only_pending_categories:
        selected = [item for item in SUBLIBS if sublib_id is None or item.sublib_id == sublib_id]
    stats = {
        "pages": 0,
        "items": 0,
        "created": 0,
        "updated": 0,
        "skipped_existing_detail": 0,
        "categories": 0,
        "errors": 0,
        "matches": 0,
        "sync_logs": 0,
        "alerts": 0,
        "linked_change_logs": 0,
    }
    with _client() as client:
        for sublib in selected:
            category = _category_for_sublib(db, source, sublib.sublib_id)
            if category:
                category.sync_status = "同步中"
                category.last_sync_started_at = datetime.now(UTC)
                category.last_sync_error = None
                db.commit()
            stats["categories"] += 1
            total_pages = max(1, sublib.total_pages_hint)
            start_page = 1
            if only_pending_categories and category and category.last_synced_page:
                start_page = min(category.last_synced_page + 1, total_pages)
            end_page = min(start_page + max_pages_per_sublib - 1, total_pages)
            category_errors = 0
            for page_index in range(start_page, end_page + 1):
                list_url = (
                    f"{BASE_URL}/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView"
                    f"&sublibID={sublib.sublib_id}&sortType=Default&abolish=&indexInfor=&PageIndex={page_index}"
                )
                try:
                    response = client.get(list_url)
                    response.raise_for_status()
                    items = parse_list_items(response.text)
                    if category:
                        category.last_seen_book_ids_hash = _book_ids_hash(items)
                        category.last_synced_page = page_index
                    stats["pages"] += 1
                except Exception:
                    stats["errors"] += 1
                    category_errors += 1
                    continue

                for item in items:
                    existing = (
                        db.query(models.StandardResource)
                        .filter(
                            models.StandardResource.source_id == source.id,
                            models.StandardResource.source_book_id == item["book_id"],
                        )
                        .first()
                    )
                    detail = None
                    should_fetch_detail = existing is None or (
                        include_detail and not existing.detail_hash
                    )
                    if should_fetch_detail:
                        try:
                            detail = fetch_detail(client, item["book_id"])
                        except Exception:
                            stats["errors"] += 1
                            category_errors += 1
                    elif include_detail and existing is not None:
                        stats["skipped_existing_detail"] += 1
                    resource, created = _upsert_resource(db, source, sublib, item, detail)
                    calibration = calibrate_resource_status(db, resource)
                    stats["matches"] += calibration["matches"]
                    stats["sync_logs"] += calibration["sync_logs"]
                    stats["alerts"] += calibration["alerts"]
                    stats["linked_change_logs"] += attach_change_logs_to_documents(db, resource)
                    stats["items"] += 1
                    stats["created" if created else "updated"] += 1
                db.commit()
            if category:
                category.last_sync_finished_at = datetime.now(UTC)
                completed = (category.last_synced_page or 0) >= total_pages
                category.sync_status = "同步失败" if category_errors else ("已同步" if completed else "待同步")
                category.last_sync_error = f"{category_errors} 个采集错误" if category_errors else None
                db.commit()
    return stats


def _guobiao_search_keyword(query: TrustedSourceSearchQuery) -> str | None:
    parts = normalize_standard_no(query.normalized_standard_no or query.standard_no)
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


def _guobiao_item_to_search_result(
    source: models.TrustedSource,
    item: dict[str, str],
    *,
    query: TrustedSourceSearchQuery,
    category_path: str,
) -> TrustedSourceSearchResult:
    standard_no = item.get("standard_no") or ""
    standard_name = item.get("title") or standard_no or item.get("book_id") or ""
    number_parts = normalize_standard_no(standard_no)
    title_score = int(SequenceMatcher(None, query.standard_name or "", standard_name).ratio() * 100)
    number_match = bool(
        query.normalized_standard_no
        and number_parts.normalized
        and query.normalized_standard_no == number_parts.normalized
    ) or bool(query.standard_no and standard_no and query.standard_no == standard_no)
    for keyword in query.keywords:
        token = keyword.strip().upper()
        if token and (token in standard_no.upper() or token in standard_name.upper()):
            number_match = True
            break
    if number_match and title_score >= 80:
        score, reason = 95, "外网实时命中：编号与标题高度一致"
    elif number_match:
        score, reason = 90, "外网实时命中：标准编号一致"
    elif title_score >= 80:
        score, reason = 80, f"外网实时命中：标题相似度 {title_score}%"
    else:
        score, reason = max(55, title_score), f"外网实时命中：标题相似度 {title_score}%"
    return TrustedSourceSearchResult(
        source_id=source.id,
        source_name=source.source_name or "国标电子书库",
        standard_no=standard_no or None,
        normalized_standard_no=number_parts.normalized,
        standard_name=standard_name,
        source_status=item.get("status"),
        detail_url=item.get("detail_url"),
        confidence_score=score,
        match_reason=reason,
        raw={
            "search_backend": "external",
            "adapter_key": "guobiao_ebook",
            "external_item_id": item.get("book_id"),
            "source_category_path": category_path,
        },
    )


INLINE_ATLAS_PATTERN = re.compile(r"(\d{2}S\d{3})\s*《\s*([^》]{2,80})\s*》", re.I)


def _guobiao_keyword_matches_item(keyword: str, item: dict[str, str]) -> bool:
    token = keyword.strip().upper()
    if not token:
        return False
    standard_no = (item.get("standard_no") or "").upper()
    title = (item.get("title") or "").upper()
    return token in standard_no or token in title


def _guobiao_inline_atlas_items(html: str, keyword: str) -> list[dict[str, str]]:
    token = keyword.strip().upper()
    if not token:
        return []
    items: list[dict[str, str]] = []
    seen_codes: set[str] = set()
    for match in INLINE_ATLAS_PATTERN.finditer(html):
        code = match.group(1).upper()
        title = _strip_html(match.group(2) or "")
        if not title or title in {"全部", "现行", "废止"}:
            continue
        if token not in {code, title.upper()} and token not in title.upper() and token not in code:
            continue
        if code in seen_codes:
            continue
        seen_codes.add(code)
        items.append(
            {
                "book_id": "",
                "standard_no": code,
                "title": title,
                "status": "现行",
                "detail_url": f"{BASE_URL}/zbooklib/sublibBook/resultlist?SiteID=1&sublibID=2118&indexInfor={quote(code)}",
            }
        )
    return items


def search_guobiao_external(
    db: Session,
    source_id: int,
    query: TrustedSourceSearchQuery,
    *,
    limit: int = 20,
) -> list[TrustedSourceSearchResult]:
    source = db.get(models.TrustedSource, source_id)
    if source is None:
        return []
    keyword = _guobiao_search_keyword(query)
    if not keyword:
        return []

    priority_sublibs = [2118, 2246, 2398, 2441]
    results: list[TrustedSourceSearchResult] = []
    seen_book_ids: set[str] = set()
    seen_codes: set[str] = set()
    with _client(timeout_seconds=30) as client:
        if re.fullmatch(r"\d{2}S\d{3}", keyword.strip(), flags=re.I):
            try:
                catalog_response = client.get(
                    f"{BASE_URL}/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView&sublibID=2118&PageIndex=1"
                )
                catalog_response.raise_for_status()
                sublib = next((item for item in SUBLIBS if item.sublib_id == 2118), None)
                category_path = sublib.category_path if sublib else ""
                for item in _guobiao_inline_atlas_items(catalog_response.text, keyword):
                    code = (item.get("standard_no") or "").upper()
                    if code in seen_codes:
                        continue
                    seen_codes.add(code)
                    results.append(_guobiao_item_to_search_result(source, item, query=query, category_path=category_path))
            except httpx.HTTPError:
                pass

        for sublib_id in priority_sublibs:
            sublib = next((item for item in SUBLIBS if item.sublib_id == sublib_id), None)
            category_path = sublib.category_path if sublib else ""
            for page_index in range(1, 4):
                list_url = (
                    f"{BASE_URL}/zbooklib/sublibBook/resultlist?SiteID=1&viewType=imgView"
                    f"&sublibID={sublib_id}&sortType=Default&abolish=&indexInfor={quote(keyword)}&PageIndex={page_index}"
                )
                try:
                    response = client.get(list_url)
                    response.raise_for_status()
                    html = response.text
                except httpx.HTTPError:
                    continue
                items = parse_list_items(html)
                for item in items:
                    if not _guobiao_keyword_matches_item(keyword, item):
                        continue
                    book_id = item.get("book_id")
                    if book_id and book_id in seen_book_ids:
                        continue
                    if book_id:
                        seen_book_ids.add(book_id)
                    results.append(_guobiao_item_to_search_result(source, item, query=query, category_path=category_path))
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
    results.sort(key=lambda item: item.confidence_score, reverse=True)
    return results[:limit]


class GuobiaoEbookAdapter(LocalIndexSearchAdapterMixin):
    adapter_key = "guobiao_ebook"

    def search_external(self, db: Session, source_id: int, query: TrustedSourceSearchQuery) -> list[TrustedSourceSearchResult]:
        return search_guobiao_external(db, source_id, query)

    def sync(self, db: Session, source_id: int, options: TrustedSourceSyncOptions) -> TrustedSourceSyncStats:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise ValueError("可信源不存在")
        if source.source_name != "国标电子书库":
            raise ValueError("guobiao_ebook 适配器只能处理国标电子书库")
        sublib_id = int(options.category_id) if options.category_id else None
        stats = sync_guobiao_resources(
            db,
            max_pages_per_sublib=options.max_pages,
            include_detail=options.include_detail,
            sublib_id=sublib_id,
            only_pending_categories=options.only_pending_categories,
            category_limit=options.category_limit,
        )
        return TrustedSourceSyncStats(**stats)


registry.register(GuobiaoEbookAdapter())
