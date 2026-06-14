"""Batch-2 file discovery, status marking, and formal-library ingest helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.batch2_admission import (
    BATCH2_STANDARD_BODY_ADAPTER_KEYS,
    batch2_pipeline_enabled,
    FILE_INGEST_ADMITTED,
    FILE_INGEST_ANNOUNCEMENT_CLUE,
    FILE_INGEST_EVIDENCE_ONLY,
    FILE_INGEST_FILE_MISSING,
    FILE_INGEST_FILE_READY,
    FILE_INGEST_MANUAL_REVIEW,
    evaluate_batch2_file_admission,
    is_batch2_announcement_adapter,
    is_batch2_standard_body_adapter,
    is_excluded_batch2_file_resource,
    record_batch2_file_evidence_only,
)
from app.batch2_file_discovery import discover_official_file_for_resource
from app.batch2_admission import is_mot_kfs_official_url, is_openstd_official_url
from app.download_service import DownloadedContent, archive_downloaded_content, fetch_url, sha256_bytes
from app.gb688_captcha_download import download_openstd_pdf, extract_hcno
from app.mot_kfs_captcha_download import download_mot_kfs_pdf_from_url
from app.settings_store import get_bool_setting


def _download_batch2_official_file(
    source: models.UrlSource,
    resource: models.StandardResource,
    *,
    timeout_seconds: int = 120,
) -> DownloadedContent:
    url = source.url
    if is_openstd_official_url(url):
        hcno = extract_hcno(url)
        if not hcno:
            raise ValueError("openstd 链接缺少 hcno")
        downloaded = download_openstd_pdf(hcno, timeout_seconds=timeout_seconds, max_attempts=5)
        return DownloadedContent(
            url=url,
            status_code=downloaded.status_code,
            content=downloaded.content,
            content_type=downloaded.content_type or "application/pdf",
            content_disposition=downloaded.content_disposition or f"{resource.standard_no or hcno}.pdf",
        )

    if is_mot_kfs_official_url(url):
        detail_url = (resource.detail_url or "").strip()
        downloaded = download_mot_kfs_pdf_from_url(
            url,
            detail_url=detail_url or None,
            timeout_seconds=timeout_seconds,
            max_attempts=5,
        )
        return DownloadedContent(
            url=url,
            status_code=downloaded.status_code,
            content=downloaded.content,
            content_type=downloaded.content_type or "application/pdf",
            content_disposition=downloaded.content_disposition or f"{resource.standard_no or 'standard'}.pdf",
        )

    fetched = fetch_url(source, timeout_seconds=timeout_seconds)
    return DownloadedContent(
        url=fetched.url,
        status_code=fetched.status_code,
        content=fetched.content,
        content_type=fetched.content_type,
        content_disposition=fetched.content_disposition,
    )


def mark_batch2_announcement_clue(resource: models.StandardResource) -> None:
    resource.file_ingest_status = FILE_INGEST_ANNOUNCEMENT_CLUE
    resource.official_file_url = None


def mark_batch2_file_missing(resource: models.StandardResource, *, reason: str | None = None) -> None:
    resource.file_ingest_status = FILE_INGEST_FILE_MISSING
    if reason:
        resource.summary = (resource.summary or "")[:400] + f" [file_missing: {reason}]"


def mark_batch2_manual_review(resource: models.StandardResource, *, reason: str) -> None:
    resource.file_ingest_status = FILE_INGEST_MANUAL_REVIEW
    resource.summary = ((resource.summary or "") + f" [manual_review: {reason}]")[:2000]


def apply_batch2_resource_file_status(
    db: Session,
    source: models.TrustedSource,
    resource: models.StandardResource,
    *,
    discover_files: bool,
    client: httpx.Client | None = None,
) -> str:
    adapter_key = source.adapter_key or ""
    if is_batch2_announcement_adapter(adapter_key) or is_excluded_batch2_file_resource(
        resource_type=resource.resource_type,
        title=resource.standard_name,
        standard_name=resource.standard_name,
        adapter_key=adapter_key,
    ):
        mark_batch2_announcement_clue(resource)
        return FILE_INGEST_ANNOUNCEMENT_CLUE

    if not is_batch2_standard_body_adapter(adapter_key):
        return resource.file_ingest_status or FILE_INGEST_MANUAL_REVIEW

    if not discover_files:
        if not resource.official_file_url:
            mark_batch2_file_missing(resource)
        return resource.file_ingest_status or FILE_INGEST_FILE_MISSING

    from app.batch2_http import make_client

    detail_url = (resource.detail_url or "").strip()
    if not detail_url:
        mark_batch2_file_missing(resource, reason="no_detail_url")
        return FILE_INGEST_FILE_MISSING

    owns_client = client is None
    http = client or make_client(referer=detail_url)
    try:
        picked = discover_official_file_for_resource(http, resource)
    except Exception as exc:
        mark_batch2_manual_review(resource, reason=str(exc)[:120])
        return FILE_INGEST_MANUAL_REVIEW
    finally:
        if owns_client:
            http.close()

    if picked is None:
        mark_batch2_file_missing(resource, reason="no_official_file_on_detail_page")
        return FILE_INGEST_FILE_MISSING

    resource.official_file_url = picked.url
    resource.pdf_trial_url = picked.url
    admission = evaluate_batch2_file_admission(
        db,
        resource=resource,
        trusted_source=source,
        official_file_url=picked.url,
    )
    if admission.evidence_only:
        resource.file_ingest_status = FILE_INGEST_EVIDENCE_ONLY
        return FILE_INGEST_EVIDENCE_ONLY
    resource.file_ingest_status = FILE_INGEST_FILE_READY
    return FILE_INGEST_FILE_READY


def discover_files_for_source(
    db: Session,
    *,
    source_id: int,
    limit: int = 100,
    only_missing: bool = True,
) -> dict:
    source = db.get(models.TrustedSource, source_id)
    if source is None or not is_batch2_standard_body_adapter(source.adapter_key):
        return {"skipped": True, "reason": "not_standard_body_adapter"}
    if not batch2_pipeline_enabled(db):
        return {"skipped": True, "reason": "batch2_pipeline_disabled"}

    query = select(models.StandardResource).where(models.StandardResource.source_id == source_id)
    if only_missing:
        query = query.where(
            models.StandardResource.file_ingest_status.in_(
                (
                    None,
                    FILE_INGEST_FILE_MISSING,
                    FILE_INGEST_MANUAL_REVIEW,
                    FILE_INGEST_EVIDENCE_ONLY,
                )
            )
        )
    resources = list(db.scalars(query.order_by(models.StandardResource.id).limit(limit)))

    stats = {
        "scanned": len(resources),
        FILE_INGEST_FILE_READY: 0,
        FILE_INGEST_FILE_MISSING: 0,
        FILE_INGEST_ANNOUNCEMENT_CLUE: 0,
        FILE_INGEST_MANUAL_REVIEW: 0,
        FILE_INGEST_EVIDENCE_ONLY: 0,
    }
    from app.batch2_http import make_client

    referer = source.base_url or "https://example.com"
    with make_client(referer=referer) as client:
        for resource in resources:
            status = apply_batch2_resource_file_status(db, source, resource, discover_files=True, client=client)
            if status in stats:
                stats[status] += 1
            else:
                stats[FILE_INGEST_MANUAL_REVIEW] += 1
    db.commit()
    return stats


def ingest_batch2_resource_file(
    db: Session,
    resource: models.StandardResource,
    *,
    storage_root,
    trusted_source: models.TrustedSource | None = None,
    defer_baidu_upload: bool = True,
) -> dict:
    if trusted_source is None:
        trusted_source = db.get(models.TrustedSource, resource.source_id)
    url = (resource.official_file_url or "").strip()
    if not url:
        mark_batch2_file_missing(resource)
        db.commit()
        return {"ok": False, "reason": FILE_INGEST_FILE_MISSING}

    source = db.scalars(select(models.UrlSource).where(models.UrlSource.url == url)).first()
    if source is None:
        source = models.UrlSource(
            url=url,
            source_name=resource.standard_name or resource.standard_no or url,
            source_unit=resource.source_name,
            source_type="第二批标准正文",
            category=resource.resource_type or "标准资源",
            check_frequency="manual",
            status=models.SourceStatus.normal.value,
            remark=f"standard_no={resource.standard_no or ''}; standard_resource_id={resource.id}; batch2_file_ingest",
        )
        db.add(source)
        db.flush()

    try:
        downloaded = _download_batch2_official_file(source, resource, timeout_seconds=120)
    except Exception as exc:
        mark_batch2_manual_review(resource, reason=f"download_failed:{exc}")
        db.commit()
        return {"ok": False, "reason": str(exc)}

    admission = evaluate_batch2_file_admission(
        db,
        resource=resource,
        trusted_source=trusted_source,
        official_file_url=url,
        file_name=resource.standard_name,
        file_title=resource.standard_name,
        file_content=downloaded.content,
        content_type=downloaded.content_type,
    )
    if admission.evidence_only or not admission.allowed:
        mark_batch2_manual_review(resource, reason=admission.reason)
        db.commit()
        return {"ok": False, "reason": admission.reason}

    if not get_bool_setting(db, "ingest_enabled", default=False):
        resource.file_ingest_status = FILE_INGEST_FILE_READY
        db.commit()
        return {"ok": False, "reason": "ingest_disabled", "file_ready": True}

    result = archive_downloaded_content(
        db,
        source,
        storage_root,
        DownloadedContent(
            url=downloaded.url,
            status_code=downloaded.status_code,
            content=downloaded.content,
            content_type=downloaded.content_type,
            content_disposition=downloaded.content_disposition,
        ),
        defer_baidu_upload=defer_baidu_upload,
    )
    if result.ok and result.document_id:
        resource.file_ingest_status = FILE_INGEST_ADMITTED
        resource.last_synced_at = datetime.now(UTC)
        db.commit()
        return {
            "ok": True,
            "document_id": result.document_id,
            "version_id": result.version_id,
            "file_hash": result.file_hash,
        }

    mark_batch2_manual_review(resource, reason=result.message or "archive_failed")
    db.commit()
    return {"ok": False, "reason": result.message or "archive_failed"}


def list_batch2_ingest_candidates(
    db: Session,
    *,
    source_id: int,
    limit: int,
    resource_ids: list[int] | None = None,
) -> list[models.StandardResource]:
    query = (
        select(models.StandardResource)
        .join(models.TrustedSource, models.TrustedSource.id == models.StandardResource.source_id)
        .where(
            models.TrustedSource.adapter_key.in_(BATCH2_STANDARD_BODY_ADAPTER_KEYS),
            models.StandardResource.source_id == source_id,
            models.StandardResource.file_ingest_status == FILE_INGEST_FILE_READY,
            models.StandardResource.official_file_url.isnot(None),
        )
        .order_by(models.StandardResource.id)
        .limit(limit)
    )
    if resource_ids:
        query = query.where(models.StandardResource.id.in_(resource_ids))
    return list(db.scalars(query))
