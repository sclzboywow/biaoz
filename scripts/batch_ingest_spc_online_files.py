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

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.governance_automation import standard_resource_ingest_eligibility_clause  # noqa: E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402
from app.baidu_upload_queue import flush_baidu_upload_queue, reset_baidu_upload_queue  # noqa: E402
from ingest_spc_online_reading_file import (  # noqa: E402
    SpcCdpSession,
    SpcOnlineUnavailableError,
    SpcRateLimitError,
    find_archived_result,
    ingest_one_spc_online_file,
)
from spc_ingest_scheduler import record_batch  # noqa: E402


TEMP_FAILURE_STATUS = "文件采集失败"
PERMANENT_UNAVAILABLE_STATUS = "文件不可在线阅读"


RESOURCE_TYPE_TO_STANDCLASS = {
    "国家标准": "CN",
    "行业标准": "QT",
    "地方标准": "DFBZ",
    "团体标准": "TC",
    "企业标准": "QYBZ",
    "计量技术规范": "JJ",
}


@dataclass(frozen=True)
class Candidate:
    resource_id: int
    standard_no: str
    standard_name: str
    detail_url: str
    standclass: str
    resource_type: str | None


def spc_source_id() -> int:
    with SessionLocal() as db:
        ensure_default_trusted_sources(db)
        source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == "spc_standard_online").first()
        if source is None:
            raise SystemExit("SPC trusted source not found")
        return source.id


def _url_source_exists():
    return exists(
        select(1)
        .select_from(models.UrlSource)
        .where(models.UrlSource.url == func.concat("spc-online-reading://", models.StandardResource.standard_no))
    )


def _archived_file_exists():
    return exists(
        select(1)
        .select_from(models.UrlSource)
        .join(
            models.DocumentVersion,
            and_(
                models.DocumentVersion.url_source_id == models.UrlSource.id,
                models.DocumentVersion.is_current.is_(True),
            ),
        )
        .where(models.UrlSource.url == func.concat("spc-online-reading://", models.StandardResource.standard_no))
    )


def _mark_file_ingest_status(resource_id: int, status: str) -> None:
    with SessionLocal() as db:
        resource = db.get(models.StandardResource, resource_id)
        if resource is None:
            return
        resource.sync_status = status
        resource.last_synced_at = datetime.now(UTC)
        db.commit()


def _mark_synced(resource_id: int) -> None:
    _mark_file_ingest_status(resource_id, "已同步")


def _mark_file_ingest_failure(resource_id: int) -> None:
    _mark_file_ingest_status(resource_id, TEMP_FAILURE_STATUS)


def _mark_file_unavailable(resource_id: int) -> None:
    _mark_file_ingest_status(resource_id, PERMANENT_UNAVAILABLE_STATUS)


def select_candidates(
    *,
    source_id: int,
    limit: int,
    category: str | None,
    force: bool,
    start_after_resource_id: int | None,
    scan_limit: int,
    failure_cooldown_hours: float,
) -> list[Candidate]:
    with SessionLocal() as db:
        statement = (
            select(models.StandardResource)
            .where(
                models.StandardResource.source_id == source_id,
                models.StandardResource.standard_no.isnot(None),
                models.StandardResource.standard_no != "",
                models.StandardResource.detail_url.isnot(None),
                models.StandardResource.detail_url != "",
            )
            .where(standard_resource_ingest_eligibility_clause())
            .order_by(models.StandardResource.id)
            .limit(min(max(scan_limit, limit * 20, 200), 5000))
        )
        if start_after_resource_id:
            statement = statement.where(models.StandardResource.id > start_after_resource_id)
        if category:
            expected_type = next((k for k, v in RESOURCE_TYPE_TO_STANDCLASS.items() if v == category), None)
            if expected_type:
                statement = statement.where(models.StandardResource.resource_type == expected_type)
        if not force:
            statement = statement.where(models.StandardResource.sync_status != PERMANENT_UNAVAILABLE_STATUS)
            statement = statement.where(~_url_source_exists())
            statement = statement.where(~_archived_file_exists())
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
        seen_standard_nos: set[str] = set()
        for resource in db.scalars(statement):
            standard_no = (resource.standard_no or "").strip()
            detail_url = (resource.detail_url or "").strip()
            if not standard_no or not detail_url or standard_no in seen_standard_nos:
                continue
            seen_standard_nos.add(standard_no)
            standclass = category or RESOURCE_TYPE_TO_STANDCLASS.get(resource.resource_type or "", "CN")
            candidates.append(
                Candidate(
                    resource_id=resource.id,
                    standard_no=standard_no,
                    standard_name=resource.standard_name,
                    detail_url=detail_url,
                    standclass=standclass,
                    resource_type=resource.resource_type,
                )
            )
            if len(candidates) >= limit:
                break
        return candidates


def _precheck_archived(item: Candidate):
    with SessionLocal() as db:
        return find_archived_result(db, item.standard_no)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-ingest authorized SPC online-reading PDFs from SPC metadata resources.")
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--category", choices=sorted(set(RESOURCE_TYPE_TO_STANDCLASS.values())))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--scan-limit", type=int, default=1000)
    parser.add_argument("--start-after-resource-id", type=int)
    parser.add_argument("--force", action="store_true", help="Re-fetch standards that already have an archived current file.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--cooldown-on-rate-limit", type=int, default=0)
    parser.add_argument("--failure-cooldown-hours", type=float, default=2.0)
    parser.add_argument("--max-consecutive-errors", type=int, default=8)
    parser.add_argument("--defer-baidu-upload", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--baidu-upload-workers", type=int, default=2)
    args = parser.parse_args()

    source_id = args.source_id or spc_source_id()
    candidates = select_candidates(
        source_id=source_id,
        limit=max(args.limit, 1),
        category=args.category,
        force=args.force,
        start_after_resource_id=args.start_after_resource_id,
        scan_limit=max(args.scan_limit, args.limit),
        failure_cooldown_hours=args.failure_cooldown_hours,
    )
    print("spc_batch_candidates " + json.dumps([item.__dict__ for item in candidates], ensure_ascii=False), flush=True)
    if args.dry_run or not candidates:
        return 0

    reset_baidu_upload_queue()
    from app.baidu_upload_queue import get_baidu_upload_queue

    get_baidu_upload_queue(workers=max(args.baidu_upload_workers, 1))
    session = SpcCdpSession(args.cdp_url)
    ok_count = 0
    skipped_count = 0
    error_count = 0
    unavailable_count = 0
    consecutive_errors = 0
    last_resource_id: int | None = None

    for index, item in enumerate(candidates, start=1):
        existing = None if args.force else _precheck_archived(item)
        if existing is not None:
            skipped_count += 1
            consecutive_errors = 0
            last_resource_id = item.resource_id
            _mark_synced(item.resource_id)
            print(
                "spc_batch_result "
                + json.dumps(
                    {
                        "index": index,
                        "resource_id": item.resource_id,
                        "standard_no": item.standard_no,
                        "ok": True,
                        "skipped": True,
                        "result": existing.model_dump(),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                flush=True,
            )
            continue

        try:
            result = ingest_one_spc_online_file(
                standard_no=item.standard_no,
                detail_url=item.detail_url,
                standclass=item.standclass,
                title=f"{item.standard_no} {item.standard_name}",
                resource_id=item.resource_id,
                session=session,
                timeout_seconds=args.timeout,
                defer_baidu_upload=args.defer_baidu_upload,
                skip_if_archived=not args.force,
            )
            ok = bool(result.ok)
            skipped = result.result == "无变化" and "跳过" in (result.message or "")
            if skipped:
                skipped_count += 1
            else:
                ok_count += 1 if ok else 0
            if ok:
                consecutive_errors = 0
                _mark_synced(item.resource_id)
            else:
                error_count += 1
                consecutive_errors += 1
                _mark_file_ingest_failure(item.resource_id)
            last_resource_id = item.resource_id
            print(
                "spc_batch_result "
                + json.dumps(
                    {
                        "index": index,
                        "resource_id": item.resource_id,
                        "standard_no": item.standard_no,
                        "ok": ok,
                        "skipped": skipped,
                        "result": result.model_dump(),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                flush=True,
            )
        except SpcRateLimitError as exc:
            error_count += 1
            consecutive_errors += 1
            last_resource_id = item.resource_id
            _mark_file_ingest_failure(item.resource_id)
            print(
                "spc_batch_result "
                + json.dumps(
                    {
                        "index": index,
                        "resource_id": item.resource_id,
                        "standard_no": item.standard_no,
                        "ok": False,
                        "rate_limited": True,
                        "error": repr(exc),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if args.cooldown_on_rate_limit > 0:
                time.sleep(args.cooldown_on_rate_limit)
            print(
                "spc_batch_summary "
                + json.dumps(
                    {
                        "ok": ok_count,
                        "skipped": skipped_count,
                        "errors": error_count,
                        "unavailable": unavailable_count,
                        "total": len(candidates),
                        "rate_limited": True,
                        "last_resource_id": last_resource_id,
                    },
                    ensure_ascii=False,
                )
            )
            if args.category:
                record_batch(args.category, ok=ok_count, skipped=skipped_count, errors=error_count, unavailable=unavailable_count, total=len(candidates))
            if args.defer_baidu_upload:
                print("spc_baidu_upload_summary " + json.dumps(flush_baidu_upload_queue(), ensure_ascii=False), flush=True)
            return 2
        except SpcOnlineUnavailableError as exc:
            unavailable_count += 1
            consecutive_errors = 0
            last_resource_id = item.resource_id
            _mark_file_unavailable(item.resource_id)
            print(
                "spc_batch_result "
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
        except IntegrityError as exc:
            skipped_count += 1
            consecutive_errors = 0
            last_resource_id = item.resource_id
            archived = _precheck_archived(item)
            if archived is not None:
                _mark_synced(item.resource_id)
                print(
                    "spc_batch_result "
                    + json.dumps(
                        {
                            "index": index,
                            "resource_id": item.resource_id,
                            "standard_no": item.standard_no,
                            "ok": True,
                            "skipped": True,
                            "duplicate_url": True,
                            "result": archived.model_dump(),
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                    flush=True,
                )
            else:
                print(
                    "spc_batch_result "
                    + json.dumps(
                        {
                            "index": index,
                            "resource_id": item.resource_id,
                            "standard_no": item.standard_no,
                            "ok": True,
                            "skipped": True,
                            "duplicate_url": True,
                            "error": repr(exc),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        except Exception as exc:
            if "UniqueViolation" in repr(exc) or "url_sources_url_key" in repr(exc):
                skipped_count += 1
                consecutive_errors = 0
                last_resource_id = item.resource_id
                archived = _precheck_archived(item)
                payload = {
                    "index": index,
                    "resource_id": item.resource_id,
                    "standard_no": item.standard_no,
                    "ok": True,
                    "skipped": True,
                    "duplicate_url": True,
                }
                if archived is not None:
                    payload["result"] = archived.model_dump()
                    _mark_synced(item.resource_id)
                else:
                    payload["error"] = repr(exc)
                print("spc_batch_result " + json.dumps(payload, ensure_ascii=False, default=str), flush=True)
                continue

            error_count += 1
            consecutive_errors += 1
            last_resource_id = item.resource_id
            _mark_file_ingest_failure(item.resource_id)
            print(
                "spc_batch_result "
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
                    "spc_batch_summary "
                    + json.dumps(
                        {
                            "ok": ok_count,
                            "skipped": skipped_count,
                            "errors": error_count,
                            "unavailable": unavailable_count,
                            "total": len(candidates),
                            "stopped_after_consecutive_errors": consecutive_errors,
                            "last_resource_id": last_resource_id,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                if args.category:
                    record_batch(args.category, ok=ok_count, skipped=skipped_count, errors=error_count, unavailable=unavailable_count, total=len(candidates))
                if args.defer_baidu_upload:
                    print("spc_baidu_upload_summary " + json.dumps(flush_baidu_upload_queue(), ensure_ascii=False), flush=True)
                return 1

        if args.delay > 0 and index < len(candidates):
            time.sleep(args.delay)

    print(
        "spc_batch_summary "
        + json.dumps(
            {
                "ok": ok_count,
                "skipped": skipped_count,
                "errors": error_count,
                "unavailable": unavailable_count,
                "total": len(candidates),
                "last_resource_id": last_resource_id,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.category:
        record_batch(args.category, ok=ok_count, skipped=skipped_count, errors=error_count, unavailable=unavailable_count, total=len(candidates))
    if args.defer_baidu_upload:
        print("spc_baidu_upload_summary " + json.dumps(flush_baidu_upload_queue(), ensure_ascii=False), flush=True)
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
