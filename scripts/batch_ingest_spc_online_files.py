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

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402
from ingest_spc_online_reading_file import (  # noqa: E402
    SpcOnlineUnavailableError,
    SpcRateLimitError,
    ingest_one_spc_online_file,
)


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


def _has_archived_file(db, standard_no: str) -> bool:
    url = f"spc-online-reading://{standard_no}"
    source = db.query(models.UrlSource).filter(models.UrlSource.url == url).first()
    if source is None:
        return False
    return (
        db.query(models.DocumentVersion)
        .filter(models.DocumentVersion.url_source_id == source.id, models.DocumentVersion.is_current.is_(True))
        .first()
        is not None
    )


def _is_in_failure_cooldown(resource: models.StandardResource, cooldown_hours: float) -> bool:
    if cooldown_hours <= 0:
        return False
    if resource.sync_status != TEMP_FAILURE_STATUS:
        return False
    if resource.last_synced_at is None:
        return True
    last_synced_at = resource.last_synced_at
    if last_synced_at.tzinfo is None:
        last_synced_at = last_synced_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - last_synced_at < timedelta(hours=cooldown_hours)


def _mark_file_ingest_status(resource_id: int, status: str, error: str) -> None:
    with SessionLocal() as db:
        resource = db.get(models.StandardResource, resource_id)
        if resource is None:
            return
        resource.sync_status = status
        resource.last_synced_at = datetime.now(UTC)
        resource.source_status_raw = resource.source_status_raw or ""
        db.commit()


def _mark_file_ingest_failure(resource_id: int, error: str) -> None:
    _mark_file_ingest_status(resource_id, TEMP_FAILURE_STATUS, error)


def _mark_file_unavailable(resource_id: int, error: str) -> None:
    _mark_file_ingest_status(resource_id, PERMANENT_UNAVAILABLE_STATUS, error)


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
            .order_by(models.StandardResource.id)
            .limit(min(max(limit, 1), max(scan_limit, limit)))
        )
        if start_after_resource_id:
            statement = statement.where(models.StandardResource.id > start_after_resource_id)
        if category:
            expected_type = next((k for k, v in RESOURCE_TYPE_TO_STANDCLASS.items() if v == category), None)
            if expected_type:
                statement = statement.where(models.StandardResource.resource_type == expected_type)
        if not force:
            statement = statement.where(models.StandardResource.sync_status != PERMANENT_UNAVAILABLE_STATUS)
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

        resources = list(db.scalars(statement))
        candidates: list[Candidate] = []
        for resource in resources:
            standard_no = (resource.standard_no or "").strip()
            detail_url = (resource.detail_url or "").strip()
            standclass = category or RESOURCE_TYPE_TO_STANDCLASS.get(resource.resource_type or "", "CN")
            if not standard_no or not detail_url:
                continue
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
        return candidates


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
    parser.add_argument("--max-consecutive-errors", type=int, default=3)
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
    if args.dry_run:
        return 0

    ok_count = 0
    error_count = 0
    consecutive_errors = 0
    last_resource_id: int | None = None
    for index, item in enumerate(candidates, start=1):
        try:
            result = ingest_one_spc_online_file(
                standard_no=item.standard_no,
                detail_url=item.detail_url,
                standclass=item.standclass,
                title=f"{item.standard_no} {item.standard_name}",
                cdp_url=args.cdp_url,
                timeout_seconds=args.timeout,
            )
            payload = {
                "index": index,
                "resource_id": item.resource_id,
                "standard_no": item.standard_no,
                "ok": result.ok,
                "result": result.model_dump(),
            }
            ok_count += 1 if result.ok else 0
            error_count += 0 if result.ok else 1
            consecutive_errors = 0 if result.ok else consecutive_errors + 1
            last_resource_id = item.resource_id
            print("spc_batch_result " + json.dumps(payload, ensure_ascii=False, default=str), flush=True)
        except SpcRateLimitError as exc:
            error_count += 1
            last_resource_id = item.resource_id
            _mark_file_ingest_failure(item.resource_id, repr(exc))
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
                print(
                    "spc_batch_rate_limit "
                    + json.dumps({"sleep_seconds": args.cooldown_on_rate_limit, "standard_no": item.standard_no}, ensure_ascii=False),
                    flush=True,
                )
                time.sleep(args.cooldown_on_rate_limit)
            print("spc_batch_summary " + json.dumps({"ok": ok_count, "errors": error_count, "total": len(candidates), "rate_limited": True, "last_resource_id": last_resource_id}, ensure_ascii=False))
            return 2
        except SpcOnlineUnavailableError as exc:
            error_count += 1
            consecutive_errors = 0
            last_resource_id = item.resource_id
            _mark_file_unavailable(item.resource_id, repr(exc))
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
        except Exception as exc:
            error_count += 1
            consecutive_errors += 1
            last_resource_id = item.resource_id
            _mark_file_ingest_failure(item.resource_id, repr(exc))
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
                            "errors": error_count,
                            "total": len(candidates),
                            "stopped_after_consecutive_errors": consecutive_errors,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                return 1
        if args.delay > 0 and index < len(candidates):
            time.sleep(args.delay)

    print(
        "spc_batch_summary "
        + json.dumps(
            {"ok": ok_count, "errors": error_count, "total": len(candidates), "last_resource_id": last_resource_id},
            ensure_ascii=False,
        )
    )
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
