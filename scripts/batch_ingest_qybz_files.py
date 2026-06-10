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

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.download_service import archive_downloaded_content
from baidu_upload_batch import add_baidu_upload_args, init_baidu_upload_workers, log_baidu_upload_summary  # noqa: E402
from app.qybz_download import QybzDownloadError, QybzDownloadUnavailableError, download_qybz_pdf
from app.settings_store import ensure_default_settings
from app.storage import configured_storage_root

ADAPTER_KEY = "samr_enterprise_standard_public"
TEMP_FAILURE_STATUS = "文件采集失败"
PERMANENT_UNAVAILABLE_STATUS = "文件不可下载"


@dataclass(frozen=True)
class Candidate:
    resource_id: int
    standard_no: str
    standard_name: str
    detail_url: str


def resolve_source(*, source_id: int | None) -> tuple[int, str]:
    with SessionLocal() as db:
        ensure_default_settings(db)
        if source_id:
            source = db.get(models.TrustedSource, source_id)
        else:
            source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == ADAPTER_KEY).first()
        if source is None:
            raise SystemExit("qybz trusted source not found")
        return source.id, source.source_name


def _has_archived_file(db, detail_url: str) -> bool:
    source = db.query(models.UrlSource).filter(models.UrlSource.url == detail_url).first()
    if source is None:
        return False
    return (
        db.query(models.DocumentVersion)
        .filter(models.DocumentVersion.url_source_id == source.id, models.DocumentVersion.is_current.is_(True))
        .first()
        is not None
    )


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
            .limit(max(limit * 10, limit, 1))
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
            detail_url = (resource.detail_url or "").strip()
            if not detail_url:
                continue
            if not force and _has_archived_file(db, detail_url):
                continue
            candidates.append(
                Candidate(
                    resource_id=resource.id,
                    standard_no=(resource.standard_no or "").strip() or resource.source_book_id or detail_url,
                    standard_name=resource.standard_name,
                    detail_url=detail_url,
                )
            )
            if len(candidates) >= limit:
                break
        return candidates


def ingest_one(
    candidate: Candidate,
    *,
    source_name: str,
    timeout_seconds: int,
    client: httpx.Client,
    defer_baidu_upload: bool,
) -> dict:
    downloaded = download_qybz_pdf(candidate.detail_url, timeout_seconds=timeout_seconds, client=client)
    settings = get_settings()
    with SessionLocal() as db:
        ensure_default_settings(db)
        resource = db.get(models.StandardResource, candidate.resource_id)
        if resource is None:
            return {"ok": False, "status": "missing_resource"}
        url_source = db.query(models.UrlSource).filter(models.UrlSource.url == candidate.detail_url).first()
        if url_source is None:
            url_source = models.UrlSource(
                url=candidate.detail_url,
                source_name=resource.standard_name or resource.standard_no or candidate.detail_url,
                source_unit=source_name,
                source_type="官方标准PDF",
                category=resource.resource_type or "企业标准",
                check_frequency="manual",
                status=models.SourceStatus.normal.value,
                remark=f"standard_no={resource.standard_no or ''}; standard_resource_id={resource.id}; provider=qybz.org.cn",
            )
            db.add(url_source)
            db.flush()
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
    parser = argparse.ArgumentParser(description="Batch-ingest qybz.org.cn enterprise standard PDFs.")
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--start-after-resource-id", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--failure-cooldown-hours", type=float, default=2.0)
    parser.add_argument("--max-consecutive-errors", type=int, default=8)
    add_baidu_upload_args(parser)
    args = parser.parse_args()

    source_id, source_name = resolve_source(source_id=args.source_id)
    candidates = select_candidates(
        source_id=source_id,
        limit=max(args.limit, 1),
        force=args.force,
        start_after_resource_id=args.start_after_resource_id,
        failure_cooldown_hours=args.failure_cooldown_hours,
    )
    print("qybz_batch_candidates " + json.dumps([item.__dict__ for item in candidates], ensure_ascii=False), flush=True)
    if args.dry_run or not candidates:
        return 0

    init_baidu_upload_workers(args)
    ok_count = error_count = consecutive_errors = 0
    last_resource_id: int | None = None
    with httpx.Client(follow_redirects=True, timeout=args.timeout) as client:
        for index, item in enumerate(candidates, start=1):
            try:
                payload = ingest_one(
                    item,
                    source_name=source_name,
                    timeout_seconds=args.timeout,
                    client=client,
                    defer_baidu_upload=args.defer_baidu_upload,
                )
                ok = bool(payload.get("ok"))
                ok_count += int(ok)
                error_count += int(not ok)
                consecutive_errors = 0 if ok else consecutive_errors + 1
                last_resource_id = item.resource_id
                print(
                    "qybz_batch_result "
                    + json.dumps(
                        {"index": index, "resource_id": item.resource_id, "standard_no": item.standard_no, **payload},
                        ensure_ascii=False,
                        default=str,
                    ),
                    flush=True,
                )
            except QybzDownloadUnavailableError as exc:
                error_count += 1
                consecutive_errors += 1
                last_resource_id = item.resource_id
                message = str(exc)
                if "极验" in message or "regLogin" in message:
                    _mark_status(item.resource_id, TEMP_FAILURE_STATUS)
                else:
                    _mark_status(item.resource_id, PERMANENT_UNAVAILABLE_STATUS)
                print(
                    "qybz_batch_result "
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
            except QybzDownloadError as exc:
                error_count += 1
                consecutive_errors += 1
                last_resource_id = item.resource_id
                _mark_status(item.resource_id, TEMP_FAILURE_STATUS)
                print(
                    "qybz_batch_result "
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
            except Exception as exc:
                error_count += 1
                consecutive_errors += 1
                last_resource_id = item.resource_id
                _mark_status(item.resource_id, TEMP_FAILURE_STATUS)
                print(
                    "qybz_batch_result "
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
                    "qybz_batch_summary "
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
                log_baidu_upload_summary("qybz", args)
                return 1
            if args.delay > 0 and index < len(candidates):
                time.sleep(args.delay)

    print(
        "qybz_batch_summary "
        + json.dumps(
            {"ok": ok_count, "errors": error_count, "total": len(candidates), "last_resource_id": last_resource_id},
            ensure_ascii=False,
        ),
        flush=True,
    )
    log_baidu_upload_summary("qybz", args)
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
