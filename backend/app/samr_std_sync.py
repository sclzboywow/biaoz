from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

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


BASE_URL = "https://std.samr.gov.cn"
OPEN_STD_URL = "https://openstd.samr.gov.cn"
OPEN_STD_STD_BASE = f"{OPEN_STD_URL}/bzgk/std"
GB688_URL = "http://c.gb688.cn"
SOURCE_NAME = "全国标准信息公共服务平台"
GB_CATEGORY_ID = "gb"
GB_CATEGORY_NAME = "国家标准"
GB_CATEGORY_PATH = "全国标准信息公共服务平台 / 国家标准"
PAGE_SIZE = 20
REQUEST_DELAY_SECONDS = float(os.getenv("SAMR_REQUEST_DELAY_SECONDS", "8"))
RATE_LIMIT_COOLDOWN_SECONDS = int(os.getenv("SAMR_RATE_LIMIT_COOLDOWN_SECONDS", "1800"))
STALE_SYNC_SECONDS = int(os.getenv("SAMR_STALE_SYNC_SECONDS", "900"))

MONITORED_CHANGE_FIELDS = {
    "standard_no",
    "standard_name",
    "source_status",
    "publish_date",
    "effective_date",
    "abolish_date",
    "summary",
    "pdf_trial_url",
}


def _client(timeout_seconds: int = 25) -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=timeout_seconds,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        },
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text.strip(" ,，、;；"):
        return None
    return text or None


def _limit(value: str | None, max_length: int) -> str | None:
    if value is None or len(value) <= max_length:
        return value
    return value[:max_length]


def _flag_enabled(value: Any) -> bool:
    return value in {1, "1", True, "true", "TRUE"}


def _delay() -> None:
    if REQUEST_DELAY_SECONDS > 0:
        time.sleep(REQUEST_DELAY_SECONDS)


def _http_error_message(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("detail")
        if message:
            return str(message)
    return f"HTTP {response.status_code}"


def _is_access_limited(exc: httpx.HTTPStatusError) -> bool:
    return exc.response.status_code == 401 or "访问过于频繁" in _http_error_message(exc)


def _is_rate_limit_message(message: str | None) -> bool:
    if not message:
        return False
    return "访问过于频繁" in message or "401" in message or "Unauthorized" in message


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _rate_limit_cooldown_active(category: models.SourceCategory | None) -> bool:
    if category is None or not _is_rate_limit_message(category.last_sync_error):
        return False
    last_attempt = _as_utc(category.last_sync_finished_at) or _as_utc(category.last_sync_started_at)
    if last_attempt is None:
        return True
    return datetime.now(UTC) - last_attempt < timedelta(seconds=RATE_LIMIT_COOLDOWN_SECONDS)


def _recover_stale_sync(category: models.SourceCategory | None) -> bool:
    if category is None or category.sync_status != "同步中":
        return False
    started_at = _as_utc(category.last_sync_started_at)
    if started_at is None:
        return False
    if datetime.now(UTC) - started_at < timedelta(seconds=STALE_SYNC_SECONDS):
        return False
    category.sync_status = "同步失败"
    category.last_sync_finished_at = datetime.now(UTC)
    category.last_sync_error = "上次同步被中断，已自动恢复"
    return True


def _sync_in_progress(category: models.SourceCategory | None) -> bool:
    if category is None or category.sync_status != "同步中":
        return False
    started_at = _as_utc(category.last_sync_started_at)
    if started_at is None:
        return False
    return datetime.now(UTC) - started_at < timedelta(seconds=STALE_SYNC_SECONDS)


def _empty_stats(categories: int = 0) -> dict[str, int]:
    return {
        "pages": 0,
        "items": 0,
        "created": 0,
        "updated": 0,
        "skipped_existing_detail": 0,
        "categories": categories,
        "errors": 0,
        "matches": 0,
        "sync_logs": 0,
        "alerts": 0,
        "linked_change_logs": 0,
    }


def _detail_url(item_id: str) -> str:
    return f"{BASE_URL}/gb/search/gbDetailed?id={item_id}"


def _open_info_url(hcno: str) -> str:
    return f"{OPEN_STD_URL}/bzgk/std/newGbInfo?hcno={hcno}"


def _online_url(hcno: str) -> str:
    return f"{OPEN_STD_STD_BASE}/showGb?type=online&hcno={hcno}"


def _download_url(hcno: str) -> str:
    return f"{OPEN_STD_STD_BASE}/showGb?type=download&hcno={hcno}"


def _review_url(hcno: str) -> str:
    return f"{OPEN_STD_URL}/bzgk/gb/review?hcno={hcno}"


def _official_links(row: dict[str, Any], item_id: str) -> dict[str, str]:
    links = {
        "std_detail": _detail_url(item_id),
    }
    hcno = _text(row.get("OPEN_HASH_CODE"))
    if hcno:
        links["openstd_detail"] = _open_info_url(hcno)
        links["online_preview"] = _online_url(hcno)
        links["download_page"] = _download_url(hcno)
        links["feedback"] = _review_url(hcno)
    return links


def _source_category_path(row: dict[str, Any]) -> str:
    parts = [GB_CATEGORY_PATH]
    for key in ("STD_NATURE", "STD_TYPE", "ICS_NAME1_FULL"):
        value = _text(row.get(key))
        if value and value not in parts:
            parts.append(value)
    return " / ".join(parts)


def _summary(row: dict[str, Any], item_id: str, detail_data: dict[str, Any] | None = None) -> str:
    detail_data = detail_data or {}
    lines = []
    fields = [
        ("标准性质", row.get("STD_NATURE")),
        ("标准领域", row.get("STD_DOMAIN")),
        ("主管部门", row.get("CD_NAME")),
        ("归口单位", row.get("ORG_SCOPE")),
        ("技术委员会", row.get("TA_CODE")),
        ("ICS", row.get("ICS_NAME1_FULL")),
        ("CCS", row.get("CCS")),
        ("起草单位", row.get("DRAFT_UNIT")),
        ("代替标准", row.get("TOTAL_REPE") or row.get("REPLACE_STD")),
        ("被代替标准", row.get("PART_REPE") or row.get("REPLACEED_STD")),
    ]
    for label, value in fields:
        text = _text(value)
        if text:
            lines.append(f"{label}：{text}")

    gbf_plan = detail_data.get("gbf_plan")
    if isinstance(gbf_plan, dict) and gbf_plan:
        lines.append("外文版：" + "、".join(str(value) for value in gbf_plan.values() if value))

    for label, url in _official_links(row, item_id).items():
        lines.append(f"{label}：{url}")
    return "\n".join(lines)


def _detail_hash(detail_payload: dict[str, Any]) -> str:
    payload = json.dumps(detail_payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _system_status(source_status: str | None) -> str:
    if source_status == "废止":
        return "来源确认废止"
    if source_status == "现行":
        return "来源确认现行"
    return "待复核"


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


def ensure_source_categories(db: Session, source: models.TrustedSource) -> None:
    existing = (
        db.query(models.SourceCategory)
        .filter(
            models.SourceCategory.source_id == source.id,
            models.SourceCategory.source_category_id == GB_CATEGORY_ID,
        )
        .first()
    )
    if existing:
        changed = False
        updates = {
            "category_name": GB_CATEGORY_NAME,
            "category_path": GB_CATEGORY_PATH,
            "source_url": f"{BASE_URL}/gb/search/gbAdvancedSearch",
        }
        for field_name, value in updates.items():
            if getattr(existing, field_name) != value:
                setattr(existing, field_name, value)
                changed = True
        if changed:
            db.commit()
        return

    db.add(
        models.SourceCategory(
            source_id=source.id,
            source_category_id=GB_CATEGORY_ID,
            category_name=GB_CATEGORY_NAME,
            category_path=GB_CATEGORY_PATH,
            source_url=f"{BASE_URL}/gb/search/gbAdvancedSearch",
            sync_status="待同步",
        )
    )
    db.commit()


def _category(db: Session, source: models.TrustedSource) -> models.SourceCategory | None:
    return (
        db.query(models.SourceCategory)
        .filter(
            models.SourceCategory.source_id == source.id,
            models.SourceCategory.source_category_id == GB_CATEGORY_ID,
        )
        .first()
    )


def fetch_list_page(client: httpx.Client, page_number: int) -> dict[str, Any]:
    response = client.get(
        f"{BASE_URL}/gb/search/gbAdvancedSearchPage",
        params={
            "tid": "2",
            "std_p6_1": "现行",
            "pageNumber": page_number,
            "pageSize": PAGE_SIZE,
        },
        headers={"Referer": f"{BASE_URL}/gb/search/gbAdvancedSearch"},
    )
    response.raise_for_status()
    return response.json()


def _search_number_token(query: TrustedSourceSearchQuery) -> str | None:
    parts = normalize_standard_no(query.normalized_standard_no or query.standard_no)
    if parts.main_no and parts.year:
        return f"{parts.main_no}-{parts.year}"
    if parts.main_no:
        return parts.main_no
    raw = _text(query.standard_no or query.normalized_standard_no)
    return raw


def _search_name_token(query: TrustedSourceSearchQuery) -> str | None:
    if query.standard_name:
        return query.standard_name.strip()[:80] or None
    for keyword in query.keywords:
        keyword = keyword.strip()
        if keyword:
            return keyword[:80]
    return None


def fetch_search_page(client: httpx.Client, query: TrustedSourceSearchQuery, *, page_size: int = 20) -> dict[str, Any]:
    params: dict[str, Any] = {
        "tid": "2",
        "pageNumber": 1,
        "pageSize": max(1, min(page_size, 50)),
    }
    number_token = _search_number_token(query)
    name_token = _search_name_token(query)
    if number_token:
        params["std_p4"] = number_token
    elif name_token:
        params["std_p8"] = name_token
    else:
        return {"total": 0, "rows": []}

    response = client.get(
        f"{BASE_URL}/gb/search/gbAdvancedSearchPage",
        params=params,
        headers={"Referer": f"{BASE_URL}/gb/search/gbAdvancedSearch"},
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("rows") if isinstance(payload, dict) else []
    if number_token and name_token and isinstance(rows, list) and not rows:
        response = client.get(
            f"{BASE_URL}/gb/search/gbAdvancedSearchPage",
            params={"tid": "2", "pageNumber": 1, "pageSize": params["pageSize"], "std_p8": name_token},
            headers={"Referer": f"{BASE_URL}/gb/search/gbAdvancedSearch"},
        )
        response.raise_for_status()
        payload = response.json()
    return payload if isinstance(payload, dict) else {"total": 0, "rows": []}


def _score_external_row(row: dict[str, Any], *, query: TrustedSourceSearchQuery) -> tuple[int, str]:
    standard_no = _text(row.get("C_STD_CODE"))
    standard_name = _text(row.get("C_C_NAME")) or _text(row.get("C_NAME")) or ""
    number_parts = normalize_standard_no(standard_no)
    title_score = int(SequenceMatcher(None, query.standard_name or "", standard_name).ratio() * 100)
    number_match = bool(
        query.normalized_standard_no
        and number_parts.normalized
        and query.normalized_standard_no == number_parts.normalized
    ) or bool(query.standard_no and standard_no and query.standard_no == standard_no)
    if number_match and title_score >= 80:
        return 95, "外网实时命中：编号与标题高度一致"
    if number_match:
        return 90, "外网实时命中：标准编号一致"
    if title_score >= 80:
        return 80, f"外网实时命中：标题相似度 {title_score}%"
    return max(55, title_score), f"外网实时命中：标题相似度 {title_score}%"


def _row_to_external_search_result(
    source: models.TrustedSource,
    row: dict[str, Any],
    *,
    query: TrustedSourceSearchQuery,
) -> TrustedSourceSearchResult | None:
    item_id = _text(row.get("id"))
    if not item_id:
        return None
    standard_no = _text(row.get("C_STD_CODE"))
    standard_name = _text(row.get("C_C_NAME")) or _text(row.get("C_NAME")) or item_id
    number_parts = normalize_standard_no(standard_no)
    hcno = _text(row.get("OPEN_HASH_CODE"))
    score, reason = _score_external_row(row, query=query)
    return TrustedSourceSearchResult(
        source_id=source.id,
        source_name=source.source_name or SOURCE_NAME,
        standard_no=standard_no,
        normalized_standard_no=number_parts.normalized,
        standard_name=standard_name,
        source_status=_text(row.get("STATE2")),
        publish_date=_parse_date(row.get("ISSUE_DATE")),
        effective_date=_parse_date(row.get("ACT_DATE")),
        abolish_date=_parse_date(row.get("D_DATE")),
        detail_url=_detail_url(item_id),
        pdf_trial_url=_online_url(hcno) if hcno and _flag_enabled(row.get("OPEN_ONLINE_STATUS")) else None,
        confidence_score=score,
        match_reason=reason,
        raw={
            "search_backend": "external",
            "adapter_key": "samr_std_public",
            "external_item_id": item_id,
            "source_category_path": _source_category_path(row),
        },
    )


def search_samr_std_external(
    db: Session,
    source_id: int,
    query: TrustedSourceSearchQuery,
    *,
    limit: int = 20,
) -> list[TrustedSourceSearchResult]:
    source = db.get(models.TrustedSource, source_id)
    if source is None:
        return []
    if not (_search_number_token(query) or _search_name_token(query)):
        return []

    with _client(timeout_seconds=30) as client:
        try:
            page = fetch_search_page(client, query, page_size=limit)
        except httpx.HTTPStatusError as exc:
            if _is_access_limited(exc):
                raise RuntimeError(f"全国标准信息公共服务平台访问受限：{_http_error_message(exc)}") from exc
            raise RuntimeError(f"全国标准信息公共服务平台搜索失败：{_http_error_message(exc)}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"全国标准信息公共服务平台网络异常：{exc}") from exc
        rows = page.get("rows") if isinstance(page, dict) else []
        if not isinstance(rows, list):
            return []

    results: list[TrustedSourceSearchResult] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = _row_to_external_search_result(source, row, query=query)
        if item is not None:
            results.append(item)
        if len(results) >= limit:
            break
    results.sort(key=lambda item: item.confidence_score, reverse=True)
    return results[:limit]


def fetch_detail(client: httpx.Client, item_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.get(
        f"{BASE_URL}/gb/search/gbDetailInfo",
        params={"id": item_id},
        headers={"Referer": _detail_url(item_id)},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {}, payload
    gb = data.get("gb")
    return gb if isinstance(gb, dict) else {}, payload


def _upsert_resource(
    db: Session,
    source: models.TrustedSource,
    row: dict[str, Any],
    detail_payload: dict[str, Any] | None,
) -> tuple[models.StandardResource, bool]:
    item_id = _text(row.get("id"))
    if not item_id:
        raise ValueError("全国标准信息公共服务平台列表项缺少 id")

    resource = (
        db.query(models.StandardResource)
        .filter(
            models.StandardResource.source_id == source.id,
            models.StandardResource.source_book_id == item_id,
        )
        .first()
    )
    created = resource is None
    if resource is None:
        resource = models.StandardResource(
            source_id=source.id,
            source_book_id=item_id,
            source_name=source.source_name,
            standard_name=_text(row.get("C_C_NAME")) or _text(row.get("C_NAME")) or item_id,
        )
        db.add(resource)
        db.flush()

    standard_no = _text(row.get("C_STD_CODE")) or resource.standard_no
    number_parts = normalize_standard_no(standard_no)
    source_status = _text(row.get("STATE2"))
    hcno = _text(row.get("OPEN_HASH_CODE"))
    detail_data = detail_payload.get("data") if isinstance(detail_payload, dict) else None
    if not isinstance(detail_data, dict):
        detail_data = {}

    updates = {
        "standard_no": standard_no,
        "raw_standard_no": number_parts.raw,
        "normalized_standard_no": number_parts.normalized,
        "standard_prefix": number_parts.prefix,
        "standard_main_no": number_parts.main_no,
        "standard_year": number_parts.year,
        "standard_revision_note": number_parts.revision_note,
        "source_status_raw": source_status,
        "standard_name": _text(row.get("C_C_NAME")) or _text(row.get("C_NAME")) or resource.standard_name,
        "resource_type": _text(row.get("STD_TYPE")) or _text(row.get("STD_NATURE")) or GB_CATEGORY_NAME,
        "source_status": source_status,
        "system_status": _system_status(source_status),
        "publish_date": _parse_date(row.get("ISSUE_DATE")),
        "effective_date": _parse_date(row.get("ACT_DATE")),
        "abolish_date": _parse_date(row.get("D_DATE")),
        "chief_editor_unit": _limit(_text(row.get("DRAFT_UNIT")), 500),
        "summary": _summary(row, item_id, detail_data),
        "keywords": _text(row.get("ICS_NAME1_FULL")),
        "source_category_path": _source_category_path(row),
        "detail_url": _detail_url(item_id),
        "pdf_trial_url": _online_url(hcno) if hcno and _flag_enabled(row.get("OPEN_ONLINE_STATUS")) else None,
        "detail_hash": _detail_hash(detail_payload or row),
        "source_confidence": source.trust_score,
        "last_synced_at": datetime.now(UTC),
        "sync_status": "已同步",
    }

    for field_name, value in updates.items():
        if not created:
            _record_change(db, resource, field_name, getattr(resource, field_name), value)
        setattr(resource, field_name, value)

    if detail_payload:
        existing_detail = (
            db.query(models.StandardDetail)
            .filter(models.StandardDetail.standard_resource_id == resource.id)
            .first()
        )
        if existing_detail is None:
            existing_detail = models.StandardDetail(standard_resource_id=resource.id)
            db.add(existing_detail)
        links = _official_links(row, item_id)
        repl_list = detail_data.get("replList")
        repled_list = detail_data.get("repledList")
        repled_plan_list = detail_data.get("repledPlanList")
        mlt_list = detail_data.get("mltList")
        video_list = detail_data.get("videoList")
        staff_list = detail_data.get("DRAFT_STAFF_LIST")
        ics_tree = detail_data.get("icsTree")
        gbf_plan = detail_data.get("gbf_plan")
        gbf_info = detail_data.get("gbf_info")
        existing_detail.catalog_text = json.dumps(
            {
                "official_links": links,
                "gb_fields": row,
            },
            ensure_ascii=False,
            default=str,
        )
        existing_detail.change_info = json.dumps(
            {
                "replaces": repl_list if isinstance(repl_list, list) else [],
                "replaced_by": repled_list if isinstance(repled_list, list) else [],
                "replaced_plan": repled_plan_list if isinstance(repled_plan_list, list) else [],
            },
            ensure_ascii=False,
            default=str,
        )
        existing_detail.related_books = json.dumps(mlt_list if isinstance(mlt_list, list) else [], ensure_ascii=False, default=str)
        existing_detail.expert_interpretation = json.dumps(
            {
                "draft_staff_list": staff_list if isinstance(staff_list, dict) else {},
                "ics_tree": ics_tree if isinstance(ics_tree, list) else [],
                "video_list": video_list if isinstance(video_list, list) else [],
                "gbf_plan": gbf_plan if isinstance(gbf_plan, dict) else {},
                "gbf_info": gbf_info if isinstance(gbf_info, dict) else {},
            },
            ensure_ascii=False,
            default=str,
        )
        existing_detail.product_info = json.dumps(detail_payload, ensure_ascii=False, default=str)

        evidence_exists = (
            db.query(models.StandardEvidence)
            .filter(
                models.StandardEvidence.standard_resource_id == resource.id,
                models.StandardEvidence.page_html_hash == resource.detail_hash,
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
                    evidence_note=f"{source.source_name} 详情接口状态证据，可信等级 {source.trust_level}",
                )
            )

    return resource, created


def sync_samr_std_resources(
    db: Session,
    source_id: int,
    max_pages: int = 1,
    include_detail: bool = True,
    only_pending_categories: bool = False,
) -> dict[str, int]:
    source = db.get(models.TrustedSource, source_id)
    if source is None:
        raise ValueError("可信源不存在")
    ensure_source_categories(db, source)
    category = _category(db, source)
    if category and _recover_stale_sync(category):
        db.commit()
    if category and _sync_in_progress(category):
        return _empty_stats(categories=1)
    if category and only_pending_categories and category.sync_status == "已同步":
        return _empty_stats()

    stats = _empty_stats(categories=1)
    if category and _rate_limit_cooldown_active(category):
        return stats
    if category:
        category.sync_status = "同步中"
        category.last_sync_started_at = datetime.now(UTC)
        category.last_sync_error = None
        db.commit()

    category_errors = 0
    with _client() as client:
        start_page = max(1, (category.last_synced_page or 0) + 1) if only_pending_categories and category else 1
        end_page = start_page + max_pages - 1
        stop_sync = False
        for page_number in range(start_page, end_page + 1):
            if stop_sync:
                break
            try:
                page = fetch_list_page(client, page_number)
                _delay()
                rows = page.get("rows") if isinstance(page, dict) else []
                if not isinstance(rows, list):
                    rows = []
                if category:
                    category.resource_count = int(page.get("total") or 0)
                    category.last_synced_page = page_number
                stats["pages"] += 1
            except httpx.HTTPStatusError as exc:
                stats["errors"] += 1
                category_errors += 1
                if category:
                    category.last_sync_error = _http_error_message(exc)
                if _is_access_limited(exc):
                    stop_sync = True
                    break
            except Exception:
                stats["errors"] += 1
                category_errors += 1
                continue

            for row in rows:
                if not isinstance(row, dict):
                    continue
                item_id = _text(row.get("id"))
                if not item_id:
                    stats["errors"] += 1
                    category_errors += 1
                    continue
                detail_payload: dict[str, Any] | None = None
                if include_detail:
                    try:
                        detail_row, detail_payload = fetch_detail(client, item_id)
                        _delay()
                        if detail_row:
                            row.update(detail_row)
                    except httpx.HTTPStatusError as exc:
                        stats["errors"] += 1
                        category_errors += 1
                        if category:
                            category.last_sync_error = _http_error_message(exc)
                        if _is_access_limited(exc):
                            stop_sync = True
                            break
                        detail_payload = None
                    except Exception:
                        stats["errors"] += 1
                        category_errors += 1
                        detail_payload = None
                if stop_sync:
                    break

                try:
                    resource, created = _upsert_resource(db, source, row, detail_payload)
                except Exception:
                    stats["errors"] += 1
                    category_errors += 1
                    continue
                calibration = calibrate_resource_status(db, resource)
                stats["matches"] += calibration["matches"]
                stats["sync_logs"] += calibration["sync_logs"]
                stats["alerts"] += calibration["alerts"]
                stats["linked_change_logs"] += attach_change_logs_to_documents(db, resource)
                stats["items"] += 1
                stats["created" if created else "updated"] += 1
            db.commit()

    if category:
        total_pages = max(1, ((category.resource_count or 0) + PAGE_SIZE - 1) // PAGE_SIZE)
        last_error = category.last_sync_error
        category.last_sync_finished_at = datetime.now(UTC)
        category.last_synced_at = category.last_sync_finished_at
        completed = (category.last_synced_page or 0) >= total_pages
        category.sync_status = "同步失败" if category_errors else ("已同步" if completed else "待同步")
        category.last_sync_error = last_error or (f"{category_errors} 个采集错误" if category_errors else None)
        db.commit()
    return stats


class SamrStdPublicAdapter(LocalIndexSearchAdapterMixin):
    adapter_key = "samr_std_public"

    def sync(self, db: Session, source_id: int, options: TrustedSourceSyncOptions) -> TrustedSourceSyncStats:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise ValueError("可信源不存在")
        if source.adapter_key != self.adapter_key:
            raise ValueError("samr_std_public 适配器只能处理全国标准信息公共服务平台")
        if options.category_id and options.category_id != GB_CATEGORY_ID:
            raise ValueError(f"全国标准信息公共服务平台暂不支持该分类：{options.category_id}")
        stats = sync_samr_std_resources(
            db,
            source_id=source.id,
            max_pages=options.max_pages,
            include_detail=options.include_detail,
            only_pending_categories=options.only_pending_categories,
        )
        return TrustedSourceSyncStats(**stats)

    def search_external(self, db: Session, source_id: int, query: TrustedSourceSearchQuery) -> list[TrustedSourceSearchResult]:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise ValueError("可信源不存在")
        if source.adapter_key != self.adapter_key:
            raise ValueError("samr_std_public 适配器只能处理全国标准信息公共服务平台")
        return search_samr_std_external(db, source_id, query, limit=20)


registry.register(SamrStdPublicAdapter())
