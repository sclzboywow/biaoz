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

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app import models
from app.standard_number import normalize_standard_no
from app.status_calibration import attach_change_logs_to_documents, calibrate_resource_status
from app.trusted_source_adapters import (
    TrustedSourceAdapter,
    TrustedSourceSearchQuery,
    TrustedSourceSearchResult,
    TrustedSourceSyncOptions,
    TrustedSourceSyncStats,
    registry,
)
from app.trusted_source_search_service import LocalIndexSearchAdapterMixin


HBDB_PAGE_SIZE = int(os.getenv("HBDB_PAGE_SIZE", "100"))
HBDB_REQUEST_DELAY_SECONDS = float(os.getenv("HBDB_REQUEST_DELAY_SECONDS", "1"))
HBDB_RETRY_ATTEMPTS = int(os.getenv("HBDB_RETRY_ATTEMPTS", "3"))
TTBZ_PAGE_SIZE = int(os.getenv("TTBZ_PAGE_SIZE", "50"))
TTBZ_REQUEST_DELAY_SECONDS = float(os.getenv("TTBZ_REQUEST_DELAY_SECONDS", "1"))
TTBZ_RETRY_ATTEMPTS = int(os.getenv("TTBZ_RETRY_ATTEMPTS", "3"))
QYBZ_REQUEST_DELAY_SECONDS = float(os.getenv("QYBZ_REQUEST_DELAY_SECONDS", "1"))


@dataclass(frozen=True)
class CategoryConfig:
    category_id: str
    category_name: str
    category_path: str
    source_url: str


@dataclass(frozen=True)
class TtbzSlice:
    key: str
    endpoint: str
    params: tuple[tuple[str, str], ...]


def _now() -> datetime:
    return datetime.now(UTC)


def _delay(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _limit(value: str | None, max_length: int) -> str | None:
    if value is None or len(value) <= max_length:
        return value
    return value[:max_length]


def _date_from_millis(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).date()
    except (TypeError, ValueError, OSError):
        return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_datetime_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) >= 10:
        return _parse_date(text[:10])
    return None


def _detail_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _external_search_keyword(query: TrustedSourceSearchQuery) -> str | None:
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


def _score_external_match(
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


def _hbdb_row_to_search_result(
    source: models.TrustedSource,
    row: dict[str, Any],
    *,
    query: TrustedSourceSearchQuery,
    adapter_key: str,
    base_url: str,
) -> TrustedSourceSearchResult | None:
    item_id = _text(row.get("pk"))
    if not item_id:
        return None
    standard_no = _text(row.get("code"))
    standard_name = _text(row.get("chName")) or standard_no or item_id
    number_parts = normalize_standard_no(standard_no)
    score, reason = _score_external_match(query=query, standard_no=standard_no, standard_name=standard_name)
    return TrustedSourceSearchResult(
        source_id=source.id,
        source_name=source.source_name or "",
        standard_no=standard_no,
        normalized_standard_no=number_parts.normalized,
        standard_name=standard_name,
        source_status=_text(row.get("status")),
        publish_date=_date_from_millis(row.get("issueDate")),
        effective_date=_date_from_millis(row.get("actDate")),
        detail_url=f"{base_url.rstrip('/')}/stdDetail/{item_id}",
        pdf_trial_url=f"{base_url.rstrip('/')}/portal/online/{item_id}",
        confidence_score=score,
        match_reason=reason,
        raw={
            "search_backend": "external",
            "adapter_key": adapter_key,
            "external_item_id": item_id,
        },
    )


def _system_status(source_status: str | None) -> str:
    if source_status and ("废止" in source_status or "失效" in source_status):
        return "来源确认废止"
    if source_status and ("现行" in source_status or "公布" in source_status):
        return "来源确认现行"
    return "待复核"


def _ensure_single_category(db: Session, source: models.TrustedSource, config: CategoryConfig) -> models.SourceCategory:
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


def _record_change(db: Session, resource: models.StandardResource, field_name: str, old_value: Any, new_value: Any) -> None:
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


def _upsert_resource(
    db: Session,
    source: models.TrustedSource,
    item_id: str,
    updates: dict[str, Any],
    evidence_summary: str | None = None,
) -> tuple[models.StandardResource, bool]:
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
            "last_synced_at": _now(),
            "sync_status": "已同步",
        }
    )
    for field_name, value in updates.items():
        if not created:
            _record_change(db, resource, field_name, getattr(resource, field_name), value)
        setattr(resource, field_name, value)

    detail_hash = updates.get("detail_hash")
    if detail_hash:
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
                models.StandardEvidence.page_html_hash == detail_hash,
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
                    page_html_hash=detail_hash,
                    evidence_note="可信源列表入库",
                )
            )

    return resource, created


class HbDbAdapter(LocalIndexSearchAdapterMixin):
    def __init__(self, adapter_key: str, base_url: str, config: CategoryConfig) -> None:
        self.adapter_key = adapter_key
        self.base_url = base_url.rstrip("/")
        self.config = config

    def _client(self) -> httpx.Client:
        return httpx.Client(
            follow_redirects=True,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.base_url}/stdList",
                "Connection": "close",
            },
        )

    def _fetch_page(self, client: httpx.Client, page: int) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, HBDB_RETRY_ATTEMPTS + 1):
            active_client = client if attempt == 1 else self._client()
            try:
                response = active_client.post(
                    f"{self.base_url}/stdQueryList",
                    data={
                        "current": page,
                        "size": HBDB_PAGE_SIZE,
                        "key": "",
                        "ministry": "",
                        "industry": "",
                        "pubdate": "",
                        "date": "",
                        "status": "",
                    },
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < HBDB_RETRY_ATTEMPTS:
                    time.sleep(min(2 * attempt, 8))
            finally:
                if attempt != 1:
                    active_client.close()
        raise RuntimeError(f"{self.config.category_name} page {page} fetch failed: {last_error}")

    def sync(self, db: Session, source_id: int, options: TrustedSourceSyncOptions) -> TrustedSourceSyncStats:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise ValueError(f"trusted source not found: {source_id}")
        category = _ensure_single_category(db, source, self.config)
        db.commit()

        stats = TrustedSourceSyncStats(categories=1)
        start_page = max(1, (category.last_synced_page or 0) + 1) if options.only_pending_categories else 1
        end_page = start_page + max(options.max_pages, 1) - 1
        category.sync_status = "同步中"
        category.last_sync_started_at = _now()
        category.last_sync_error = None
        db.commit()

        errors = 0
        with self._client() as client:
            for page_number in range(start_page, end_page + 1):
                try:
                    payload = self._fetch_page(client, page_number)
                except Exception as exc:
                    errors += 1
                    category.last_sync_error = str(exc)
                    break
                records = payload.get("records") if isinstance(payload, dict) else []
                if not isinstance(records, list):
                    records = []
                category.resource_count = int(payload.get("total") or category.resource_count or 0)
                total_pages = max(1, ((category.resource_count or 0) + HBDB_PAGE_SIZE - 1) // HBDB_PAGE_SIZE)
                if page_number > total_pages or not records:
                    break
                category.last_synced_page = page_number
                stats.pages += 1
                for row in records:
                    if not isinstance(row, dict) or not row.get("pk"):
                        continue
                    standard_no = _text(row.get("code"))
                    source_status = _text(row.get("status"))
                    detail_url = f"{self.base_url}/stdDetail/{row['pk']}"
                    online_url = f"{self.base_url}/portal/online/{row['pk']}"
                    summary = "\n".join(
                        part
                        for part in [
                            f"备案号：{_text(row.get('recordNo'))}" if _text(row.get("recordNo")) else "",
                            f"主管部门：{_text(row.get('chargeDept'))}" if _text(row.get("chargeDept")) else "",
                            f"行业/地区：{_text(row.get('industry'))}" if _text(row.get("industry")) else "",
                        ]
                        if part
                    )
                    resource, created = _upsert_resource(
                        db,
                        source,
                        str(row["pk"]),
                        {
                            "standard_no": standard_no,
                            "source_status_raw": source_status,
                            "standard_name": _text(row.get("chName")) or standard_no or str(row["pk"]),
                            "resource_type": self.config.category_name,
                            "source_status": source_status,
                            "system_status": _system_status(source_status),
                            "publish_date": _date_from_millis(row.get("issueDate")),
                            "effective_date": _date_from_millis(row.get("actDate")),
                            "storage_date": _date_from_millis(row.get("recordDate")),
                            "chief_editor_unit": _limit(_text(row.get("chargeDept")), 500),
                            "summary": summary,
                            "keywords": _text(row.get("industry")),
                            "source_category_path": self.config.category_path,
                            "detail_url": detail_url,
                            "pdf_trial_url": online_url,
                            "detail_hash": _detail_hash(row),
                        },
                        evidence_summary=summary,
                    )
                    stats.created += 1 if created else 0
                    stats.updated += 0 if created else 1
                    stats.items += 1
                    calibration = calibrate_resource_status(db, resource)
                    stats.matches += calibration["matches"]
                    stats.sync_logs += calibration["sync_logs"]
                    stats.alerts += calibration["alerts"]
                    stats.linked_change_logs += attach_change_logs_to_documents(db, resource)
                db.commit()
                _delay(HBDB_REQUEST_DELAY_SECONDS)

        category.last_sync_finished_at = _now()
        category.last_synced_at = category.last_sync_finished_at
        total_pages = max(1, ((category.resource_count or 0) + HBDB_PAGE_SIZE - 1) // HBDB_PAGE_SIZE)
        category.sync_status = "同步失败" if errors else ("已同步" if (category.last_synced_page or 0) >= total_pages else "待同步")
        stats.errors = errors
        db.commit()
        return stats

    def search_external(self, db: Session, source_id: int, query: TrustedSourceSearchQuery) -> list[TrustedSourceSearchResult]:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            return []
        keyword = _external_search_keyword(query)
        if not keyword:
            return []
        with self._client() as client:
            response = client.post(
                f"{self.base_url}/stdQueryList",
                data={
                    "current": 1,
                    "size": 20,
                    "key": keyword,
                    "ministry": "",
                    "industry": "",
                    "pubdate": "",
                    "date": "",
                    "status": "",
                },
            )
            response.raise_for_status()
            payload = response.json()
        records = payload.get("records") if isinstance(payload, dict) else []
        if not isinstance(records, list):
            return []
        results: list[TrustedSourceSearchResult] = []
        for row in records:
            if not isinstance(row, dict):
                continue
            item = _hbdb_row_to_search_result(
                source,
                row,
                query=query,
                adapter_key=self.adapter_key,
                base_url=self.base_url,
            )
            if item is not None:
                results.append(item)
        results.sort(key=lambda item: item.confidence_score, reverse=True)
        return results[:20]


class TtbzAdapter(LocalIndexSearchAdapterMixin):
    adapter_key = "samr_group_standard_public"

    config = CategoryConfig(
        "group_standard",
        "团体标准",
        "全国标准信息公共服务平台 / 团体标准信息平台",
        "https://www.ttbz.org.cn/standard.html",
    )

    def _client(self) -> httpx.Client:
        return httpx.Client(
            follow_redirects=True,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
                "Referer": "https://www.ttbz.org.cn/standard.html",
            },
        )

    def _fetch_dict_ids(self, client: httpx.Client, category_type: str) -> list[str]:
        try:
            response = client.post(
                "https://www.ttbz.org.cn/cms-proxy/ms/portal/standardInfo/getPortalFirstLevelDictList",
                params={"categoryType": category_type},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        data = payload.get("data") if isinstance(payload, dict) else []
        items = data.get("list") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        return [str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")]

    def _slices(self, client: httpx.Client) -> list[TtbzSlice]:
        slices: list[TtbzSlice] = [
            TtbzSlice("latest", "getPortalStandardList", ()),
            TtbzSlice("open", "getPortalStandardList", (("isOpen", "1"),)),
            TtbzSlice("not_open", "getPortalStandardList", (("isOpen", "0"),)),
            TtbzSlice("sale", "getPortalStandardList", (("isSale", "1"),)),
            TtbzSlice("not_sale", "getPortalStandardList", (("isSale", "0"),)),
            TtbzSlice("disabled", "getDisabledStandardList", ()),
        ]
        for category_id in self._fetch_dict_ids(client, "CN"):
            slices.append(TtbzSlice(f"ccsl:{category_id}", "getPortalStandardList", (("ccsl", category_id),)))
        for category_id in self._fetch_dict_ids(client, "EN"):
            slices.append(TtbzSlice(f"icsl:{category_id}", "getPortalStandardList", (("icsl", category_id),)))
        return slices

    def _fetch_page(self, client: httpx.Client, slice_config: TtbzSlice, page: int) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, TTBZ_RETRY_ATTEMPTS + 1):
            try:
                response = client.post(
                    f"https://www.ttbz.org.cn/cms-proxy/ms/portal/standardInfo/{slice_config.endpoint}",
                    data={
                        "pageNo": page,
                        "pageSize": TTBZ_PAGE_SIZE,
                        **dict(slice_config.params),
                    },
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < TTBZ_RETRY_ATTEMPTS:
                    time.sleep(min(2 * attempt, 8))
        raise RuntimeError(f"group standard slice {slice_config.key} page {page} fetch failed: {last_error}")

    def sync(self, db: Session, source_id: int, options: TrustedSourceSyncOptions) -> TrustedSourceSyncStats:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise ValueError(f"trusted source not found: {source_id}")
        category = _ensure_single_category(db, source, self.config)
        category.sync_status = "同步中"
        category.last_sync_started_at = _now()
        category.last_sync_error = None
        db.commit()

        stats = TrustedSourceSyncStats(categories=1)
        errors = 0
        seen_ids: set[str] = set()
        with self._client() as client:
            for slice_index, slice_config in enumerate(self._slices(client), start=1):
                for page_number in range(1, max(options.max_pages, 1) + 1):
                    try:
                        payload = self._fetch_page(client, slice_config, page_number)
                    except Exception as exc:
                        errors += 1
                        category.last_sync_error = str(exc)
                        break
                    data = payload.get("data") if isinstance(payload, dict) else {}
                    rows = data.get("rows") if isinstance(data, dict) else []
                    if not isinstance(rows, list):
                        rows = []
                    reported_total = int(data.get("total") or 0) if isinstance(data, dict) else 0
                    category.resource_count = max(category.resource_count or 0, reported_total, len(seen_ids))
                    total_pages = max(1, (reported_total + TTBZ_PAGE_SIZE - 1) // TTBZ_PAGE_SIZE) if reported_total else 1
                    if page_number > total_pages or not rows:
                        break
                    category.last_synced_page = slice_index
                    stats.pages += 1
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        item_id = _text(row.get("standardUniqueId") or row.get("id"))
                        if not item_id or item_id in seen_ids:
                            continue
                        seen_ids.add(item_id)
                        standard_no = _text(row.get("standardNo"))
                        source_status = _text(row.get("standardStatusName") or row.get("statusName"))
                        detail_url = f"https://www.ttbz.org.cn/standardDetail/{item_id}.html"
                        summary = "\n".join(
                            part
                            for part in [
                                f"社会团体：{_text(row.get('organName'))}" if _text(row.get("organName")) else "",
                                f"组织代码：{_text(row.get('organCode'))}" if _text(row.get("organCode")) else "",
                                f"ICS：{_text(row.get('icsl1Name'))}" if _text(row.get("icsl1Name")) else "",
                                f"CCS：{_text(row.get('ccsl1Name'))}" if _text(row.get("ccsl1Name")) else "",
                                f"是否公开：{_text(row.get('isOpenName'))}" if _text(row.get("isOpenName")) else "",
                                f"切片：{slice_config.key}",
                            ]
                            if part
                        )
                        resource, created = _upsert_resource(
                            db,
                            source,
                            item_id,
                            {
                                "standard_no": standard_no,
                                "source_status_raw": source_status,
                                "standard_name": _text(row.get("standardTitleCn")) or standard_no or item_id,
                                "resource_type": self.config.category_name,
                                "source_status": source_status,
                                "system_status": _system_status(source_status),
                                "publish_date": _parse_date(row.get("publishDate") or row.get("filePublishDate")),
                                "effective_date": _parse_date(row.get("implementDate")),
                                "abolish_date": _parse_date(row.get("abolishDate")),
                                "chief_editor_unit": _limit(_text(row.get("organName")), 500),
                                "summary": summary,
                                "keywords": _text(row.get("icsl1Name") or row.get("ccsl1Name")),
                                "source_category_path": self.config.category_path,
                                "detail_url": detail_url,
                                "detail_hash": _detail_hash(row),
                            },
                            evidence_summary=summary,
                        )
                        stats.created += 1 if created else 0
                        stats.updated += 0 if created else 1
                        stats.items += 1
                        calibration = calibrate_resource_status(db, resource)
                        stats.matches += calibration["matches"]
                        stats.sync_logs += calibration["sync_logs"]
                        stats.alerts += calibration["alerts"]
                        stats.linked_change_logs += attach_change_logs_to_documents(db, resource)
                    db.commit()
                    _delay(TTBZ_REQUEST_DELAY_SECONDS)
                if errors:
                    break

        category.last_sync_finished_at = _now()
        category.last_synced_at = category.last_sync_finished_at
        stored_count = (
            db.query(models.StandardResource)
            .filter(models.StandardResource.source_id == source.id)
            .count()
        )
        category.resource_count = max(category.resource_count or 0, len(seen_ids), stored_count)
        category.sync_status = "同步失败" if errors else "已同步"
        stats.errors = errors
        db.commit()
        return stats

    def search_external(self, db: Session, source_id: int, query: TrustedSourceSearchQuery) -> list[TrustedSourceSearchResult]:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            return []
        keyword = _external_search_keyword(query)
        if not keyword:
            return []
        search_payloads: list[dict[str, str]] = [{"standardNo": keyword}]
        if query.standard_name and re.search(r"[\u4e00-\u9fff]", query.standard_name):
            search_payloads.append({"standardName": query.standard_name.strip()[:80]})
        if re.search(r"[\u4e00-\u9fff]", keyword):
            search_payloads.append({"standardName": keyword[:80]})

        results: list[TrustedSourceSearchResult] = []
        seen_ids: set[str] = set()
        with self._client() as client:
            for payload in search_payloads:
                try:
                    response = client.post(
                        "https://www.ttbz.org.cn/cms-proxy/ms/portal/standardInfo/getPortalStandardList",
                        data={"pageNo": 1, "pageSize": 20, **payload},
                    )
                    response.raise_for_status()
                    body = response.json()
                except (httpx.HTTPError, ValueError):
                    continue
                data = body.get("data") if isinstance(body, dict) else {}
                rows = data.get("rows") if isinstance(data, dict) else []
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    item_id = _text(row.get("standardUniqueId") or row.get("id"))
                    if not item_id or item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                    standard_no = _text(row.get("standardNo"))
                    standard_name = _text(row.get("standardName")) or item_id
                    number_parts = normalize_standard_no(standard_no)
                    score, reason = _score_external_match(query=query, standard_no=standard_no, standard_name=standard_name)
                    results.append(
                        TrustedSourceSearchResult(
                            source_id=source.id,
                            source_name=source.source_name or "",
                            standard_no=standard_no,
                            normalized_standard_no=number_parts.normalized,
                            standard_name=standard_name,
                            source_status=_text(row.get("standardStatusName") or row.get("statusName")),
                            detail_url=f"https://www.ttbz.org.cn/standardDetail/{item_id}.html",
                            confidence_score=score,
                            match_reason=reason,
                            raw={
                                "search_backend": "external",
                                "adapter_key": self.adapter_key,
                                "external_item_id": item_id,
                            },
                        )
                    )
        results.sort(key=lambda item: item.confidence_score, reverse=True)
        return results[:20]


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _parse_qybz_standard_text(value: str | None) -> tuple[str | None, str | None]:
    text = _clean_text(value)
    if not text:
        return None, None
    if "《" in text and "》" in text:
        standard_no, rest = text.split("《", 1)
        return standard_no.strip() or None, rest.split("》", 1)[0].strip() or None
    return None, text


def _qybz_label_value(text_lines: list[str], label: str) -> str | None:
    for index, line in enumerate(text_lines):
        if line == label and index + 1 < len(text_lines):
            return text_lines[index + 1]
    return None


def _parse_qybz_home_items(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, str]] = []
    for row in soup.find_all("tr"):
        detail_link = row.find("a", href=lambda href: href and "toDetail(" in href)
        if detail_link is None:
            continue
        href = detail_link.get("href") or ""
        match = href.split("toDetail(", 1)[-1].split(")", 1)[0].strip("'\" ")
        if not match:
            continue
        cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
        if len(cells) < 5:
            continue
        standard_no, standard_name = _parse_qybz_standard_text(cells[2])
        items.append(
            {
                "id": match,
                "company": cells[1],
                "standard_text": cells[2],
                "standard_no": standard_no or "",
                "standard_name": standard_name or cells[2],
                "published_at": cells[3],
                "status": cells[4],
            }
        )
    return items


def _parse_qybz_detail(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    lines = [_clean_text(line) for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    values: dict[str, str] = {}
    product_values: dict[str, str] = {}
    for table_index, table in enumerate(soup.find_all("table")):
        rows = [
            [_clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            for row in table.find_all("tr")
        ]
        if table_index in {0, 1}:
            for row in rows:
                for offset in range(0, len(row) - 1, 2):
                    if row[offset]:
                        values[row[offset]] = row[offset + 1]
        if table_index == 2 and len(rows) >= 2:
            headers = rows[0]
            first_data_row = rows[1]
            product_values = {
                header: first_data_row[index]
                for index, header in enumerate(headers)
                if header and index < len(first_data_row)
            }
    standard_name = values.get("标准名称") or _qybz_label_value(lines, "标准名称")
    standard_no = values.get("标准编号") or _qybz_label_value(lines, "标准编号")
    company = values.get("机构名称") or _qybz_label_value(lines, "机构名称")
    credit_code = values.get("统一社会信用代码") or _qybz_label_value(lines, "统一社会信用代码")
    area = values.get("行政区划") or _qybz_label_value(lines, "行政区划")
    published_at = values.get("公开时间") or _qybz_label_value(lines, "公开时间")
    product_name = product_values.get("产品名称")
    generic_name = product_values.get("通用名")
    brand = product_values.get("品牌")
    barcode = product_values.get("条码")
    spec = product_values.get("规格")
    model = product_values.get("型号")
    category = product_values.get("分类")
    commitment = None
    for line in lines:
        if "自我承诺" in line or "真实性、准确性、合法性" in line:
            commitment = line
            break
    summary_parts = [
        f"企业：{company}" if company else "",
        f"统一社会信用代码：{credit_code}" if credit_code else "",
        f"行政区划：{area}" if area else "",
        f"产品名称：{product_name}" if product_name else "",
        f"通用名：{generic_name}" if generic_name else "",
        f"品牌：{brand}" if brand else "",
        f"条码：{barcode}" if barcode else "",
        f"规格：{spec}" if spec else "",
        f"型号：{model}" if model else "",
        f"分类：{category}" if category else "",
        commitment or "",
    ]
    return {
        "standard_name": standard_name,
        "standard_no": standard_no,
        "company": company,
        "credit_code": credit_code,
        "area": area,
        "published_at": published_at,
        "product_name": product_name,
        "generic_name": generic_name,
        "brand": brand,
        "barcode": barcode,
        "spec": spec,
        "model": model,
        "category": category,
        "commitment": commitment,
        "summary": "\n".join(part for part in summary_parts if part),
        "detail_hash": hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest(),
    }


class QybzAdapter(LocalIndexSearchAdapterMixin):
    adapter_key = "samr_enterprise_standard_public"

    config = CategoryConfig(
        "enterprise_standard",
        "企业标准",
        "全国标准信息公共服务平台 / 企业标准信息公共服务平台",
        "https://www.qybz.org.cn/",
    )

    def _client(self) -> httpx.Client:
        return httpx.Client(
            follow_redirects=True,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
                "Referer": "https://www.qybz.org.cn/",
            },
        )

    def sync(self, db: Session, source_id: int, options: TrustedSourceSyncOptions) -> TrustedSourceSyncStats:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise ValueError(f"trusted source not found: {source_id}")
        category = _ensure_single_category(db, source, self.config)
        category.sync_status = "同步中"
        category.last_sync_started_at = _now()
        category.last_sync_error = None
        db.commit()

        stats = TrustedSourceSyncStats(categories=1)
        errors = 0
        with self._client() as client:
            try:
                response = client.get("https://www.qybz.org.cn/")
                response.raise_for_status()
                items = _parse_qybz_home_items(response.text)
            except Exception as exc:
                items = []
                errors += 1
                category.last_sync_error = str(exc)

            category.resource_count = len(items)
            category.last_synced_page = 1
            stats.pages = 1 if items else 0
            for item in items:
                detail: dict[str, Any] = {}
                detail_url = f"https://www.qybz.org.cn/user/detail/{item['id']}"
                if options.include_detail:
                    try:
                        detail_response = client.get(detail_url, headers={"Referer": "https://www.qybz.org.cn/"})
                        detail_response.raise_for_status()
                        detail = _parse_qybz_detail(detail_response.text)
                    except Exception as exc:
                        errors += 1
                        category.last_sync_error = str(exc)
                    _delay(QYBZ_REQUEST_DELAY_SECONDS)

                standard_no = _text(detail.get("standard_no")) or _text(item.get("standard_no"))
                standard_name = _text(detail.get("standard_name")) or _text(item.get("standard_name")) or item["id"]
                company = _text(detail.get("company")) or _text(item.get("company"))
                source_status = _text(item.get("status")) or "已公开"
                summary = _text(detail.get("summary")) or (
                    f"企业：{company}\n公开时间：{item.get('published_at')}\n执行标准：{item.get('standard_text')}"
                )
                resource, created = _upsert_resource(
                    db,
                    source,
                    item["id"],
                    {
                        "standard_no": standard_no,
                        "source_status_raw": source_status,
                        "standard_name": standard_name,
                        "resource_type": self.config.category_name,
                        "source_status": source_status,
                        "system_status": _system_status(source_status),
                        "publish_date": _parse_datetime_date(detail.get("published_at") or item.get("published_at")),
                        "chief_editor_unit": _limit(company, 500),
                        "summary": summary,
                        "keywords": _text(detail.get("product_name") or detail.get("category")),
                        "source_category_path": self.config.category_path,
                        "detail_url": detail_url,
                        "detail_hash": detail.get("detail_hash") or _detail_hash(item),
                    },
                    evidence_summary=summary,
                )
                stats.created += 1 if created else 0
                stats.updated += 0 if created else 1
                stats.items += 1
                calibration = calibrate_resource_status(db, resource)
                stats.matches += calibration["matches"]
                stats.sync_logs += calibration["sync_logs"]
                stats.alerts += calibration["alerts"]
                stats.linked_change_logs += attach_change_logs_to_documents(db, resource)
                db.commit()

        category.last_sync_finished_at = _now()
        category.last_synced_at = category.last_sync_finished_at
        stored_count = db.query(models.StandardResource).filter(models.StandardResource.source_id == source_id).count()
        category.resource_count = stored_count
        category.sync_status = "同步失败" if errors and not stats.items else "部分同步"
        if stats.items:
            category.last_sync_error = (
                "企业站全量搜索入口需要极验校验；当前仅采集首页公开列表与详情页结构化数据，不代表全量完成。"
            )
        stats.errors = errors
        db.commit()
        return stats


registry.register(
    HbDbAdapter(
        "samr_industry_standard_public",
        "https://hbba.sacinfo.org.cn",
        CategoryConfig(
            "industry_standard",
            "行业标准",
            "全国标准信息公共服务平台 / 行业标准信息服务平台",
            "https://hbba.sacinfo.org.cn/stdList",
        ),
    )
)
registry.register(
    HbDbAdapter(
        "samr_local_standard_public",
        "https://dbba.sacinfo.org.cn",
        CategoryConfig(
            "local_standard",
            "地方标准",
            "全国标准信息公共服务平台 / 地方标准信息服务平台",
            "https://dbba.sacinfo.org.cn/stdList",
        ),
    )
)
registry.register(TtbzAdapter())
registry.register(QybzAdapter())

