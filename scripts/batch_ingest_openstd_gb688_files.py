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
from sqlalchemy import and_, exists, func, or_, select

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.download_service import archive_downloaded_content
from baidu_upload_batch import add_baidu_upload_args, init_baidu_upload_workers, log_baidu_upload_summary  # noqa: E402
from app.gb688_captcha_download import (
    Gb688CaptchaError,
    Gb688CaptchaIncorrectError,
    Gb688DownloadUnavailableError,
    download_gb688_pdf,
    extract_hcno,
)
from app.samr_std_sync import _download_url
from app.settings_store import ensure_default_settings
from app.storage import check_storage_root, configured_storage_root

SOURCE_NAME = "国家标准信息公共服务平台（全量）"
ADAPTER_KEY = "samr_gb_all_public"
TEMP_FAILURE_STATUS = "文件采集失败"
PERMANENT_UNAVAILABLE_STATUS = "文件不可下载"


@dataclass(frozen=True)
class Candidate:
    resource_id: int
    standard_no: str
    standard_name: str
    hcno: str
    download_url: str


def openstd_source_id() -> int:
    with SessionLocal() as db:
        ensure_default_settings(db)
        source = (
            db.query(models.TrustedSource)
            .filter(
                or_(
                    models.TrustedSource.adapter_key == ADAPTER_KEY,
                    models.TrustedSource.source_name == SOURCE_NAME,
                )
            )
            .order_by(models.TrustedSource.id)
            .first()
        )
        if source is None:
            raise SystemExit("openstd/guojiabiaozhun trusted source not found")
        return source.id


def _has_archived_file(db, download_url: str) -> bool:
    source = db.query(models.UrlSource).filter(models.UrlSource.url == download_url).first()
    if source is None:
        return False
    return (
        db.query(models.DocumentVersion)
        .filter(models.DocumentVersion.url_source_id == source.id, models.DocumentVersion.is_current.is_(True))
        .first()
        is not None
    )


def _is_in_failure_cooldown(resource: models.StandardResource, cooldown_hours: float) -> bool:
    if cooldown_hours <= 0 or resource.sync_status != TEMP_FAILURE_STATUS:
        return False
    if resource.last_synced_at is None:
        return True
    last_synced_at = resource.last_synced_at
    if last_synced_at.tzinfo is None:
        last_synced_at = last_synced_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - last_synced_at < timedelta(hours=cooldown_hours)


def _mark_status(resource_id: int, status: str) -> None:
    with SessionLocal() as db:
        resource = db.get(models.StandardResource, resource_id)
        if resource is None:
            return
        resource.sync_status = status
        resource.last_synced_at = datetime.now(UTC)
        db.commit()


def _resource_hcno(resource: models.StandardResource) -> str | None:
    return extract_hcno(resource.summary, resource.pdf_trial_url, resource.detail_url)


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
            .limit(max(limit, 1))
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
            hcno = _resource_hcno(resource)
            if not hcno:
                continue
            download_url = _download_url(hcno)
            if not force and _has_archived_file(db, download_url):
                continue
            standard_no = (resource.standard_no or "").strip() or hcno
            candidates.append(
                Candidate(
                    resource_id=resource.id,
                    standard_no=standard_no,
                    standard_name=resource.standard_name,
                    hcno=hcno,
                    download_url=download_url,
                )
            )
            if len(candidates) >= limit:
                break
        return candidates


def _create_or_get_url_source(db, url: str, resource: models.StandardResource) -> models.UrlSource:
    source = db.query(models.UrlSource).filter(models.UrlSource.url == url).first()
    if source:
        return source
    source = models.UrlSource(
        url=url,
        source_name=resource.standard_name or resource.standard_no or url,
        source_unit=SOURCE_NAME,
        source_type="官方标准PDF",
        category="国家标准",
        check_frequency="manual",
        status=models.SourceStatus.normal.value,
        remark=(
            f"standard_no={resource.standard_no or ''}; standard_resource_id={resource.id}; "
            f"provider=openstd.gb688; captcha=auto"
        ),
    )
    db.add(source)
    db.flush()
    return source


def ingest_one(
    candidate: Candidate,
    *,
    timeout_seconds: int,
    max_attempts: int,
    client: httpx.Client,
    defer_baidu_upload: bool,
) -> dict:
    downloaded = download_gb688_pdf(
        candidate.hcno,
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
        url_source = _create_or_get_url_source(db, candidate.download_url, resource)
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
    parser = argparse.ArgumentParser(description="Batch-ingest openstd.samr.gov.cn GB688 PDFs with automatic captcha OCR.")
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--start-after-resource-id", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("GB688_CAPTCHA_MAX_ATTEMPTS", "3")))
    parser.add_argument("--failure-cooldown-hours", type=float, default=2.0)
    parser.add_argument("--max-consecutive-errors", type=int, default=5)
    add_baidu_upload_args(parser)
    args = parser.parse_args()

    source_id = args.source_id or openstd_source_id()
    candidates = select_candidates(
        source_id=source_id,
        limit=max(args.limit, 1),
        force=args.force,
        start_after_resource_id=args.start_after_resource_id,
        failure_cooldown_hours=args.failure_cooldown_hours,
    )
    print("openstd_batch_candidates " + json.dumps([item.__dict__ for item in candidates], ensure_ascii=False), flush=True)
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
                    "openstd_batch_result "
                    + json.dumps(
                        {"index": index, "resource_id": item.resource_id, "standard_no": item.standard_no, **payload},
                        ensure_ascii=False,
                        default=str,
                    ),
                    flush=True,
                )
            except Gb688DownloadUnavailableError as exc:
                error_count += 1
                consecutive_errors += 1
                last_resource_id = item.resource_id
                _mark_status(item.resource_id, TEMP_FAILURE_STATUS if "gb688.cn" in repr(exc) else PERMANENT_UNAVAILABLE_STATUS)
                print(
                    "openstd_batch_result "
                    + json.dumps(
                        {
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
            except (Gb688CaptchaIncorrectError, Gb688CaptchaError) as exc:
                error_count += 1
                consecutive_errors += 1
                last_resource_id = item.resource_id
                _mark_status(item.resource_id, TEMP_FAILURE_STATUS)
                print(
                    "openstd_batch_result "
                    + json.dumps(
                        {
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
                    "openstd_batch_result "
                    + json.dumps(
                        {
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
                    "openstd_batch_summary "
                    + json.dumps(
                        {
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
                log_baidu_upload_summary("openstd", args)
                return 1

            if args.delay > 0 and index < len(candidates):
                time.sleep(args.delay)

    print(
        "openstd_batch_summary "
        + json.dumps({"ok": ok_count, "errors": error_count, "total": len(candidates), "last_resource_id": last_resource_id}, ensure_ascii=False),
        flush=True,
    )
    log_baidu_upload_summary("openstd", args)
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
