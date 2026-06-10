from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(BACKEND)

import httpx
from sqlalchemy import and_, or_, select

PORTAL_PREFLIGHT_CLIENT: httpx.Client | None = None

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.download_service import archive_downloaded_content
from baidu_upload_batch import add_baidu_upload_args, init_baidu_upload_workers, log_baidu_upload_summary  # noqa: E402
from app.samr_portal_captcha_download import (
    SamrPortalCaptchaError,
    SamrPortalCaptchaIncorrectError,
    SamrPortalDownloadUnavailableError,
    download_sacinfo_portal_pdf,
    extract_portal_info,
    portal_online_url,
)
from app.settings_store import ensure_default_settings
from app.storage import configured_storage_root

ADAPTER_KEYS = {
    "industry": "samr_industry_standard_public",
    "local": "samr_local_standard_public",
}
TEMP_FAILURE_STATUS = "文件采集失败"
PERMANENT_UNAVAILABLE_STATUS = "文件不可下载"


@dataclass(frozen=True)
class Candidate:
    resource_id: int
    standard_no: str
    standard_name: str
    base_url: str
    pk: str
    canonical_url: str


def resolve_source(*, source_id: int | None, adapter_key: str | None) -> tuple[int, str, str]:
    with SessionLocal() as db:
        ensure_default_settings(db)
        query = db.query(models.TrustedSource)
        if source_id:
            source = query.filter(models.TrustedSource.id == source_id).first()
        elif adapter_key:
            source = query.filter(models.TrustedSource.adapter_key == adapter_key).first()
        else:
            raise SystemExit("require --source-id or --adapter-key")
        if source is None:
            raise SystemExit("trusted source not found")
        return source.id, source.source_name, source.adapter_key or adapter_key or ""


def _has_archived_file(db, canonical_url: str) -> bool:
    source = db.query(models.UrlSource).filter(models.UrlSource.url == canonical_url).first()
    if source is None:
        return False
    return (
        db.query(models.DocumentVersion)
        .filter(models.DocumentVersion.url_source_id == source.id, models.DocumentVersion.is_current.is_(True))
        .first()
        is not None
    )


def _portal_has_captcha_entry(base_url: str, pk: str, referer: str | None) -> bool:
    global PORTAL_PREFLIGHT_CLIENT
    if PORTAL_PREFLIGHT_CLIENT is None:
        PORTAL_PREFLIGHT_CLIENT = httpx.Client(follow_redirects=True, timeout=30)
    online_url = portal_online_url(base_url, pk)
    page = PORTAL_PREFLIGHT_CLIENT.get(
        online_url,
        headers={"Accept": "text/html,*/*", "Referer": referer or online_url},
    )
    page.raise_for_status()
    return "/portal/validate-code" in page.text


def _mark_status(resource_id: int, status: str) -> None:
    with SessionLocal() as db:
        resource = db.get(models.StandardResource, resource_id)
        if resource is None:
            return
        resource.sync_status = status
        resource.last_synced_at = datetime.now(UTC)
        db.commit()


def select_candidates(
    *,
    source_id: int,
    limit: int,
    force: bool,
    start_after_resource_id: int | None,
    failure_cooldown_hours: float,
) -> list[Candidate]:
    with SessionLocal() as db:
        statement = (
            select(models.StandardResource)
            .where(models.StandardResource.source_id == source_id)
            .order_by(models.StandardResource.id)
            .limit(max(limit * 30, limit, 1))
        )
        if start_after_resource_id:
            statement = statement.where(models.StandardResource.id > start_after_resource_id)
        if not force:
            statement = statement.where(models.StandardResource.sync_status != PERMANENT_UNAVAILABLE_STATUS)
            if failure_cooldown_hours > 0:
                cooldown_cutoff = datetime.now(UTC) - timedelta(hours=failure_cooldown_hours)
                statement = statement.where(
                    or_(
                        models.StandardResource.sync_status != TEMP_FAILURE_STATUS,
                        and_(
                            models.StandardResource.last_synced_at.isnot(None),
                            models.StandardResource.last_synced_at < cooldown_cutoff,
                        ),
                    )
                )

        candidates: list[Candidate] = []
        for resource in db.scalars(statement):
            portal = extract_portal_info(
                resource.pdf_trial_url,
                resource.detail_url,
                source_book_id=resource.source_book_id,
            )
            if not portal:
                continue
            base_url, pk = portal
            canonical_url = portal_online_url(base_url, pk)
            if not force and _has_archived_file(db, canonical_url):
                continue
            if not force:
                try:
                    if not _portal_has_captcha_entry(base_url, pk, resource.detail_url):
                        continue
                except httpx.HTTPError:
                    continue
            standard_no = (resource.standard_no or "").strip() or pk
            candidates.append(
                Candidate(
                    resource_id=resource.id,
                    standard_no=standard_no,
                    standard_name=resource.standard_name,
                    base_url=base_url,
                    pk=pk,
                    canonical_url=canonical_url,
                )
            )
            if len(candidates) >= limit:
                break
        return candidates


def _create_or_get_url_source(
    db,
    canonical_url: str,
    resource: models.StandardResource,
    source_name: str,
) -> models.UrlSource:
    source = db.query(models.UrlSource).filter(models.UrlSource.url == canonical_url).first()
    if source:
        return source
    source = models.UrlSource(
        url=canonical_url,
        source_name=resource.standard_name or resource.standard_no or canonical_url,
        source_unit=source_name,
        source_type="官方标准PDF",
        category=resource.resource_type or "标准资源",
        check_frequency="manual",
        status=models.SourceStatus.normal.value,
        remark=(
            f"standard_no={resource.standard_no or ''}; standard_resource_id={resource.id}; "
            f"provider=sacinfo.portal; captcha=auto"
        ),
    )
    db.add(source)
    db.flush()
    return source


def ingest_one(
    candidate: Candidate,
    *,
    source_name: str,
    timeout_seconds: int,
    max_attempts: int,
    client: httpx.Client,
    defer_baidu_upload: bool,
) -> dict:
    downloaded = download_sacinfo_portal_pdf(
        candidate.base_url,
        candidate.pk,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        client=client,
    )
    settings = get_settings()
    with SessionLocal() as db:
        ensure_default_settings(db)
        resource = db.get(models.StandardResource, candidate.resource_id)
        if resource is None:
            return {"ok": False, "status": "missing_resource"}
        url_source = _create_or_get_url_source(db, candidate.canonical_url, resource, source_name)
        storage_root = configured_storage_root(db, settings.storage_root)
        result = archive_downloaded_content(
            db,
            url_source,
            storage_root,
            downloaded,
            defer_baidu_upload=defer_baidu_upload,
        )
        if result.ok:
            resource.sync_status = "已同步"
            resource.last_synced_at = datetime.now(UTC)
            db.commit()
        return {"ok": result.ok, "status": "archived" if result.ok else "archive_failed", "result": result.model_dump()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-ingest hbba/dbba sacinfo portal PDFs with automatic captcha OCR.")
    parser.add_argument("--platform", choices=sorted(ADAPTER_KEYS), help="industry=hbba, local=dbba")
    parser.add_argument("--adapter-key")
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--start-after-resource-id", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("SACINFO_CAPTCHA_MAX_ATTEMPTS", "3")))
    parser.add_argument("--failure-cooldown-hours", type=float, default=2.0)
    parser.add_argument("--max-consecutive-errors", type=int, default=5)
    add_baidu_upload_args(parser)
    args = parser.parse_args()

    adapter_key = args.adapter_key
    if args.platform and not adapter_key:
        adapter_key = ADAPTER_KEYS[args.platform]
    source_id, source_name, resolved_adapter = resolve_source(source_id=args.source_id, adapter_key=adapter_key)
    candidates = select_candidates(
        source_id=source_id,
        limit=max(args.limit, 1),
        force=args.force,
        start_after_resource_id=args.start_after_resource_id,
        failure_cooldown_hours=args.failure_cooldown_hours,
    )
    print(
        "sacinfo_batch_candidates "
        + json.dumps(
            [{"platform": resolved_adapter, **item.__dict__} for item in candidates],
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.dry_run or not candidates:
        return 0

    init_baidu_upload_workers(args)
    ok_count = 0
    error_count = 0
    consecutive_errors = 0
    last_resource_id: int | None = None
    with httpx.Client(follow_redirects=True, timeout=args.timeout) as client:
        for index, item in enumerate(candidates, start=1):
            try:
                payload = ingest_one(
                    item,
                    source_name=source_name,
                    timeout_seconds=args.timeout,
                    max_attempts=args.max_attempts,
                    client=client,
                    defer_baidu_upload=args.defer_baidu_upload,
                )
                ok = bool(payload.get("ok"))
                ok_count += 1 if ok else 0
                error_count += 0 if ok else 1
                consecutive_errors = 0 if ok else consecutive_errors + 1
                last_resource_id = item.resource_id
                print(
                    "sacinfo_batch_result "
                    + json.dumps(
                        {
                            "platform": resolved_adapter,
                            "index": index,
                            "resource_id": item.resource_id,
                            "standard_no": item.standard_no,
                            **payload,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                    flush=True,
                )
            except SamrPortalDownloadUnavailableError as exc:
                error_count += 1
                consecutive_errors += 1
                last_resource_id = item.resource_id
                message = str(exc)
                if "未提供验证码下载入口" in message:
                    pass
                else:
                    _mark_status(item.resource_id, PERMANENT_UNAVAILABLE_STATUS)
                print(
                    "sacinfo_batch_result "
                    + json.dumps(
                        {
                            "platform": resolved_adapter,
                            "index": index,
                            "resource_id": item.resource_id,
                            "standard_no": item.standard_no,
                            "ok": False,
                            "unavailable": True,
                            "error": repr(exc),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except (SamrPortalCaptchaIncorrectError, SamrPortalCaptchaError) as exc:
                error_count += 1
                consecutive_errors += 1
                last_resource_id = item.resource_id
                _mark_status(item.resource_id, TEMP_FAILURE_STATUS)
                print(
                    "sacinfo_batch_result "
                    + json.dumps(
                        {
                            "platform": resolved_adapter,
                            "index": index,
                            "resource_id": item.resource_id,
                            "standard_no": item.standard_no,
                            "ok": False,
                            "captcha_error": True,
                            "error": repr(exc),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception as exc:
                error_count += 1
                consecutive_errors += 1
                last_resource_id = item.resource_id
                _mark_status(item.resource_id, TEMP_FAILURE_STATUS)
                print(
                    "sacinfo_batch_result "
                    + json.dumps(
                        {
                            "platform": resolved_adapter,
                            "index": index,
                            "resource_id": item.resource_id,
                            "standard_no": item.standard_no,
                            "ok": False,
                            "error": repr(exc),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

            if args.max_consecutive_errors > 0 and consecutive_errors >= args.max_consecutive_errors:
                print(
                    "sacinfo_batch_summary "
                    + json.dumps(
                        {
                            "platform": resolved_adapter,
                            "ok": ok_count,
                            "errors": error_count,
                            "total": len(candidates),
                            "stopped_after_consecutive_errors": consecutive_errors,
                            "last_resource_id": last_resource_id,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                log_baidu_upload_summary("sacinfo", args)
                return 1

            if args.delay > 0 and index < len(candidates):
                time.sleep(args.delay)

    print(
        "sacinfo_batch_summary "
        + json.dumps(
            {
                "platform": resolved_adapter,
                "ok": ok_count,
                "errors": error_count,
                "total": len(candidates),
                "last_resource_id": last_resource_id,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    log_baidu_upload_summary("sacinfo", args)
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
