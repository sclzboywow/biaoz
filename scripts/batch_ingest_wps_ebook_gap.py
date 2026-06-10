"""
批量归档 WPS 国标电子书 PDF 缺口（库中尚无 PDF）到正式库，并同步百度网盘。

用法:
  backend/.venv/Scripts/python.exe scripts/batch_ingest_wps_ebook_gap.py --dry-run
  backend/.venv/Scripts/python.exe scripts/batch_ingest_wps_ebook_gap.py --limit 5
  backend/.venv/Scripts/python.exe scripts/batch_ingest_wps_ebook_gap.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(BACKEND)

import httpx
from sqlalchemy import or_, select, text

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.download_service import DownloadedContent, archive_downloaded_content
from app.standard_number import normalize_standard_no
from app.settings_store import ensure_default_settings
from app.storage import configured_storage_root
from baidu_upload_batch import add_baidu_upload_args, init_baidu_upload_workers, log_baidu_upload_summary
from report_wps_ebook_gap import extract_standard_no

LOG_PATH = ROOT / "logs" / "wps-ebook-gap-ingest.log"
FAILURE_PATH = ROOT / "logs" / "wps-ebook-gap-ingest-failures.jsonl"


@dataclass(frozen=True)
class GapCandidate:
    wps_record_id: str
    file_no: str | None
    file_name: str | None
    impl_status: str | None
    link_url: str


def _load_library_sets(db) -> tuple[set[str], set[str], set[str]]:
    urls_in_lib = {
        row[0]
        for row in db.execute(
            text(
                """
                SELECT DISTINCT us.url
                FROM url_sources us
                JOIN document_versions dv ON dv.url_source_id = us.id
                WHERE us.url IS NOT NULL AND btrim(us.url) <> ''
                """
            )
        ).all()
        if row[0]
    }
    pdf_trial_in_lib = {
        row[0]
        for row in db.execute(
            text(
                """
                SELECT DISTINCT sr.pdf_trial_url
                FROM standard_resources sr
                JOIN standard_file_matches sfm ON sfm.standard_resource_id = sr.id
                JOIN document_versions dv ON dv.id = sfm.document_version_id
                WHERE sr.pdf_trial_url IS NOT NULL AND btrim(sr.pdf_trial_url) <> ''
                """
            )
        ).all()
        if row[0]
    }
    std_in_lib = {
        row[0]
        for row in db.execute(
            text(
                """
                SELECT DISTINCT COALESCE(d.normalized_standard_no, d.standard_no)
                FROM documents d
                JOIN document_versions dv ON dv.document_id = d.id
                WHERE COALESCE(d.normalized_standard_no, d.standard_no) IS NOT NULL
                """
            )
        ).all()
        if row[0]
    }
    return urls_in_lib, pdf_trial_in_lib, std_in_lib


def _has_archived_pdf(db, link_url: str) -> bool:
    source = db.query(models.UrlSource).filter(models.UrlSource.url == link_url).first()
    if source is None:
        return False
    return (
        db.query(models.DocumentVersion)
        .filter(models.DocumentVersion.url_source_id == source.id)
        .first()
        is not None
    )


def select_gap_candidates(*, limit: int | None = None) -> list[GapCandidate]:
    with SessionLocal() as db:
        urls_in_lib, pdf_trial_in_lib, std_in_lib = _load_library_sets(db)
        rows = db.execute(
            text(
                """
                SELECT wps_record_id, file_no, file_name, impl_status, link_url
                FROM wps_standard_query_records
                WHERE link_url LIKE '%ebook.chinabuilding.com.cn%'
                  AND link_url LIKE '%/pdf/%'
                ORDER BY serial_no ASC, wps_record_id ASC
                """
            )
        ).mappings().all()

        candidates: list[GapCandidate] = []
        seen_links: set[str] = set()
        for row in rows:
            link = (row["link_url"] or "").strip()
            if not link or link in seen_links:
                continue
            std_no = extract_standard_no(row["file_no"], row["file_name"])
            has_file = (
                link in urls_in_lib
                or link in pdf_trial_in_lib
                or (std_no is not None and std_no in std_in_lib)
            )
            if has_file:
                continue
            if _has_archived_pdf(db, link):
                continue
            seen_links.add(link)
            candidates.append(
                GapCandidate(
                    wps_record_id=row["wps_record_id"],
                    file_no=row["file_no"],
                    file_name=row["file_name"],
                    impl_status=row["impl_status"],
                    link_url=link,
                )
            )
            if limit and len(candidates) >= limit:
                break
        return candidates


def _guobiao_source(db) -> models.TrustedSource:
    source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == "guobiao_ebook").first()
    if source is None:
        raise RuntimeError("guobiao_ebook 可信源不存在")
    return source


def _resolve_standard_resource(
    db,
    *,
    trusted_source: models.TrustedSource,
    candidate: GapCandidate,
) -> models.StandardResource:
    resource = db.scalars(
        select(models.StandardResource).where(
            models.StandardResource.source_id == trusted_source.id,
            models.StandardResource.pdf_trial_url == candidate.link_url,
        )
    ).first()
    if resource is not None:
        return resource

    number_parts = normalize_standard_no(candidate.file_no)
    if number_parts.normalized:
        resource = db.scalars(
            select(models.StandardResource).where(
                models.StandardResource.source_id == trusted_source.id,
                or_(
                    models.StandardResource.normalized_standard_no == number_parts.normalized,
                    models.StandardResource.standard_no == candidate.file_no,
                ),
            )
        ).first()
        if resource is not None:
            if not resource.pdf_trial_url:
                resource.pdf_trial_url = candidate.link_url
            return resource

    impl = candidate.impl_status or "未知"
    resource = models.StandardResource(
        source_id=trusted_source.id,
        source_name=trusted_source.source_name,
        standard_no=candidate.file_no,
        raw_standard_no=number_parts.raw,
        normalized_standard_no=number_parts.normalized,
        standard_prefix=number_parts.prefix,
        standard_main_no=number_parts.main_no,
        standard_year=number_parts.year,
        standard_revision_note=number_parts.revision_note,
        standard_name=candidate.file_name or candidate.file_no or candidate.link_url,
        resource_type="国标电子书库资源",
        source_status=impl,
        source_status_raw=impl,
        system_status="来源确认废止" if impl == "废止" else "来源确认现行",
        source_category_path="国标电子书库 / WPS补档",
        pdf_trial_url=candidate.link_url,
        source_confidence=trusted_source.trust_score,
        last_synced_at=datetime.now(UTC),
        sync_status="待同步",
    )
    db.add(resource)
    db.flush()
    return resource


def _create_or_get_url_source(
    db,
    *,
    candidate: GapCandidate,
    resource: models.StandardResource,
) -> models.UrlSource:
    source = db.query(models.UrlSource).filter(models.UrlSource.url == candidate.link_url).first()
    if source:
        return source
    source = models.UrlSource(
        url=candidate.link_url,
        source_name=resource.standard_name or resource.standard_no or candidate.link_url,
        source_unit=resource.source_name or "国标电子书库",
        source_type="官方标准PDF",
        category=resource.resource_type or "国标电子书库资源",
        check_frequency="manual",
        status=models.SourceStatus.normal.value,
        remark=(
            f"standard_no={resource.standard_no or candidate.file_no or ''}; "
            f"standard_resource_id={resource.id}; "
            f"provider=guobiao.ebook; wps_record_id={candidate.wps_record_id}"
        ),
    )
    db.add(source)
    db.flush()
    return source


def download_ebook_pdf(url: str, *, client: httpx.Client) -> DownloadedContent:
    response = client.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
            "Accept": "application/pdf,*/*",
            "Referer": "https://ebook.chinabuilding.com.cn/",
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}")
    content = response.content
    if not content.startswith(b"%PDF"):
        content_type = response.headers.get("content-type") or "unknown"
        raise RuntimeError(f"非 PDF 内容: {content_type}")
    return DownloadedContent(
        status_code=response.status_code,
        url=str(response.url),
        content=content,
        content_type=response.headers.get("content-type"),
        content_disposition=response.headers.get("content-disposition"),
    )


def ingest_one(
    candidate: GapCandidate,
    *,
    client: httpx.Client,
    defer_baidu_upload: bool,
    timeout_seconds: int,
) -> dict:
    downloaded = download_ebook_pdf(candidate.link_url, client=client)
    settings = get_settings()
    with SessionLocal() as db:
        ensure_default_settings(db)
        if _has_archived_pdf(db, candidate.link_url):
            return {"ok": True, "status": "already_archived", "wps_record_id": candidate.wps_record_id}

        trusted_source = _guobiao_source(db)
        resource = _resolve_standard_resource(db, trusted_source=trusted_source, candidate=candidate)
        url_source = _create_or_get_url_source(db, candidate=candidate, resource=resource)
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
            if not resource.pdf_trial_url:
                resource.pdf_trial_url = candidate.link_url
            db.execute(
                text(
                    """
                    UPDATE wps_standard_query_records
                    SET governance_status = 'ingested'
                    WHERE wps_record_id = :rid
                    """
                ),
                {"rid": candidate.wps_record_id},
            )
            db.commit()
        return {
            "ok": result.ok,
            "status": result.result if result.ok else "archive_failed",
            "message": result.message,
            "wps_record_id": candidate.wps_record_id,
            "link_url": candidate.link_url,
            "document_id": result.document_id,
            "version_id": result.version_id,
        }


def _log_line(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(UTC).isoformat()} {message}"
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch ingest WPS guobiao ebook PDF gaps.")
    parser.add_argument("--limit", type=int, default=0, help="0 = all gaps")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-consecutive-errors", type=int, default=20)
    add_baidu_upload_args(parser, default_defer=True)
    args = parser.parse_args()

    limit = args.limit or None
    candidates = select_gap_candidates(limit=limit)
    _log_line(f"candidates={len(candidates)} dry_run={args.dry_run}")

    if args.dry_run:
        for item in candidates[:20]:
            print(
                json.dumps(
                    {
                        "wps_record_id": item.wps_record_id,
                        "file_no": item.file_no,
                        "file_name": item.file_name,
                        "link_url": item.link_url,
                    },
                    ensure_ascii=False,
                )
            )
        if len(candidates) > 20:
            print(f"... and {len(candidates) - 20} more")
        return 0

    init_baidu_upload_workers(args)
    stats = {"ok": 0, "fail": 0, "skip": 0}
    consecutive_errors = 0

    with httpx.Client(follow_redirects=True, timeout=args.timeout) as client:
        for index, candidate in enumerate(candidates, start=1):
            try:
                outcome = ingest_one(
                    candidate,
                    client=client,
                    defer_baidu_upload=bool(args.defer_baidu_upload),
                    timeout_seconds=args.timeout,
                )
                if outcome.get("ok"):
                    stats["ok"] += 1
                    consecutive_errors = 0
                    _log_line(
                        f"[{index}/{len(candidates)}] ok {candidate.wps_record_id} "
                        f"{outcome.get('status')} doc={outcome.get('document_id')}"
                    )
                else:
                    stats["fail"] += 1
                    consecutive_errors += 1
                    _log_line(
                        f"[{index}/{len(candidates)}] fail {candidate.wps_record_id} "
                        f"{outcome.get('message')}"
                    )
                    FAILURE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    with FAILURE_PATH.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(outcome, ensure_ascii=False) + "\n")
            except Exception as exc:
                stats["fail"] += 1
                consecutive_errors += 1
                payload = {
                    "ok": False,
                    "wps_record_id": candidate.wps_record_id,
                    "link_url": candidate.link_url,
                    "error": str(exc),
                }
                _log_line(f"[{index}/{len(candidates)}] error {candidate.wps_record_id} {exc}")
                with FAILURE_PATH.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

            if consecutive_errors >= args.max_consecutive_errors:
                _log_line(f"abort: consecutive_errors={consecutive_errors}")
                break
            if args.delay > 0:
                time.sleep(args.delay)

    log_baidu_upload_summary("wps_ebook_gap", args)
    _log_line(f"done stats={json.dumps(stats, ensure_ascii=False)}")
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
