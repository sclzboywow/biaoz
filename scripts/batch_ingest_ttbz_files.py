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
from app.settings_store import ensure_default_settings
from app.storage import configured_storage_root
from app.http_proxy import resolve_ttbz_http_proxy
from app.ttbz_browser_session import apply_ttbz_browser_auth, check_ttbz_browser_login, resolve_ttbz_cdp_url
from app.ttbz_download import (
    TtbzDownloadError,
    TtbzDownloadUnavailableError,
    canonical_ttbz_url,
    download_ttbz_pdf,
    extract_ttbz_unique_id,
)


def build_ttbz_client(*, timeout: int, proxy: str | None = None, cdp_url: str | None = None) -> httpx.Client:
    kwargs: dict = {"follow_redirects": True, "timeout": timeout}
    resolved_proxy = (proxy or "").strip() or resolve_ttbz_http_proxy()
    if resolved_proxy:
        kwargs["proxy"] = resolved_proxy
    client = httpx.Client(**kwargs)
    resolved_cdp = resolve_ttbz_cdp_url(cdp_url)
    if resolved_cdp:
        try:
            auth = apply_ttbz_browser_auth(client, cdp_url=resolved_cdp)
            print(
                "ttbz_browser_auth "
                + json.dumps({"cdp_url": resolved_cdp, **auth}, ensure_ascii=False),
                flush=True,
            )
        except Exception as exc:
            print(
                "ttbz_browser_cookies "
                + json.dumps({"cdp_url": resolved_cdp, "error": repr(exc)}, ensure_ascii=False),
                flush=True,
            )
    return client

ADAPTER_KEY = "samr_group_standard_public"
TEMP_FAILURE_STATUS = "文件采集失败"
PERMANENT_UNAVAILABLE_STATUS = "文件不可下载"


@dataclass(frozen=True)
class Candidate:
    resource_id: int
    standard_no: str
    standard_name: str
    unique_id: str
    detail_url: str


def resolve_source(*, source_id: int | None) -> tuple[int, str]:
    with SessionLocal() as db:
        ensure_default_settings(db)
        if source_id:
            source = db.get(models.TrustedSource, source_id)
        else:
            source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == ADAPTER_KEY).first()
        if source is None:
            raise SystemExit("ttbz trusted source not found")
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
            .limit(max(limit * 20, limit, 1))
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
            unique_id = extract_ttbz_unique_id(resource.detail_url, source_book_id=resource.source_book_id)
            if not unique_id:
                continue
            detail_url = resource.detail_url or canonical_ttbz_url(unique_id)
            if not force and _has_archived_file(db, detail_url):
                continue
            candidates.append(
                Candidate(
                    resource_id=resource.id,
                    standard_no=(resource.standard_no or "").strip() or unique_id,
                    standard_name=resource.standard_name,
                    unique_id=unique_id,
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
    downloaded = download_ttbz_pdf(
        candidate.unique_id,
        detail_url=candidate.detail_url,
        standard_no=candidate.standard_no,
        standard_name=candidate.standard_name,
        timeout_seconds=timeout_seconds,
        client=client,
    )
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
                category=resource.resource_type or "团体标准",
                check_frequency="manual",
                status=models.SourceStatus.normal.value,
                remark=f"standard_no={resource.standard_no or ''}; standard_resource_id={resource.id}; provider=ttbz.org.cn",
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
    parser = argparse.ArgumentParser(description="Batch-ingest ttbz.org.cn group standard PDFs.")
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--start-after-resource-id", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--failure-cooldown-hours", type=float, default=2.0)
    parser.add_argument("--max-consecutive-errors", type=int, default=8)
    parser.add_argument("--http-proxy", default="", help="HTTP/SOCKS proxy for ttbz.org.cn, e.g. socks5://127.0.0.1:18080")
    parser.add_argument(
        "--cdp-url",
        default="",
        help="TTBZ member Chrome CDP URL for login cookies (default env TTBZ_CDP_URL or http://127.0.0.1:9223)",
    )
    add_baidu_upload_args(parser)
    args = parser.parse_args()

    login_status = check_ttbz_browser_login(cdp_url=resolve_ttbz_cdp_url(args.cdp_url or None))
    print("ttbz_browser_login " + json.dumps(login_status, ensure_ascii=False), flush=True)

    source_id, source_name = resolve_source(source_id=args.source_id)
    candidates = select_candidates(
        source_id=source_id,
        limit=max(args.limit, 1),
        force=args.force,
        start_after_resource_id=args.start_after_resource_id,
        failure_cooldown_hours=args.failure_cooldown_hours,
    )
    print(
        "ttbz_batch_candidates "
        + json.dumps(
            {
                "count": len(candidates),
                "first_resource_id": candidates[0].resource_id if candidates else None,
                "last_resource_id": candidates[-1].resource_id if candidates else None,
                "first_standard_no": candidates[0].standard_no if candidates else None,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.dry_run or not candidates:
        return 0

    init_baidu_upload_workers(args)
    ok_count = error_count = consecutive_errors = 0
    last_resource_id: int | None = None
    with build_ttbz_client(timeout=args.timeout, proxy=args.http_proxy or None, cdp_url=args.cdp_url or None) as client:
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
                    "ttbz_batch_result "
                    + json.dumps(
                        {"index": index, "resource_id": item.resource_id, "standard_no": item.standard_no, **payload},
                        ensure_ascii=False,
                        default=str,
                    ),
                    flush=True,
                )
            except TtbzDownloadUnavailableError as exc:
                error_count += 1
                consecutive_errors = 0
                last_resource_id = item.resource_id
                _mark_status(item.resource_id, PERMANENT_UNAVAILABLE_STATUS)
                print(
                    "ttbz_batch_result "
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
            except TtbzDownloadError as exc:
                error_count += 1
                consecutive_errors += 1
                last_resource_id = item.resource_id
                _mark_status(item.resource_id, TEMP_FAILURE_STATUS)
                print(
                    "ttbz_batch_result "
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
                    "ttbz_batch_result "
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
                    "ttbz_batch_summary "
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
                log_baidu_upload_summary("ttbz", args)
                return 1
            if args.delay > 0 and index < len(candidates):
                time.sleep(args.delay)

    print(
        "ttbz_batch_summary "
        + json.dumps(
            {"ok": ok_count, "errors": error_count, "total": len(candidates), "last_resource_id": last_resource_id},
            ensure_ascii=False,
        ),
        flush=True,
    )
    log_baidu_upload_summary("ttbz", args)
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
