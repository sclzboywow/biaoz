from __future__ import annotations

import concurrent.futures
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import exists, func
from sqlalchemy.exc import OperationalError

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.download_service import DownloadFailure, DownloadedContent, archive_downloaded_content, fetch_url, record_download_failure  # noqa: E402
from app.storage import check_storage_root  # noqa: E402


TARGET_FILES = int(os.getenv("TARGET_FILES", "2000"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "48"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "6"))
TIMEOUT_SECONDS = int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "20"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "5000"))
DB_RETRY_ATTEMPTS = int(os.getenv("DB_RETRY_ATTEMPTS", "5"))
DB_RETRY_SLEEP_SECONDS = float(os.getenv("DB_RETRY_SLEEP_SECONDS", "2"))


@dataclass(frozen=True)
class SourceCandidate:
    id: int
    url: str


def is_database_locked(exc: Exception) -> bool:
    return isinstance(exc, OperationalError) and "database is locked" in str(exc).lower()


def with_db_retry(operation, label: str):
    for attempt in range(1, DB_RETRY_ATTEMPTS + 1):
        try:
            return operation()
        except Exception as exc:
            if not is_database_locked(exc) or attempt >= DB_RETRY_ATTEMPTS:
                raise
            delay = DB_RETRY_SLEEP_SECONDS * attempt
            print(f"db_locked label={label} attempt={attempt}/{DB_RETRY_ATTEMPTS} retry_in={delay:.1f}s", flush=True)
            time.sleep(delay)


def count_versions() -> int:
    with SessionLocal() as db:
        return int(db.query(func.count(models.DocumentVersion.id)).scalar() or 0)


def select_sources(limit: int) -> list[SourceCandidate]:
    bad_statuses = {
        models.SourceStatus.error.value,
        models.SourceStatus.invalid.value,
        models.SourceStatus.login_required.value,
    }
    with SessionLocal() as db:
        rows = (
            db.query(models.UrlSource.id, models.UrlSource.url)
            .filter(~exists().where(models.DocumentVersion.url_source_id == models.UrlSource.id))
            .filter(~models.UrlSource.status.in_(bad_statuses))
            .order_by(models.UrlSource.id)
            .limit(limit)
            .all()
        )
        return [SourceCandidate(id=row.id, url=row.url) for row in rows]


def persist_result(source_id: int, result: DownloadedContent | DownloadFailure, storage_root: Path) -> bool:
    def operation() -> bool:
        with SessionLocal() as db:
            source = db.get(models.UrlSource, source_id)
            if source is None:
                return False
            if isinstance(result, DownloadFailure):
                record_download_failure(db, source, result)
                return False
            outcome = archive_downloaded_content(db, source, storage_root, result)
            return bool(outcome.ok and outcome.version_id and outcome.change_type == models.ChangeType.created.value)

    return bool(with_db_retry(operation, f"persist:{source_id}"))


def main() -> None:
    settings = get_settings()
    attempts = success = failed = skipped = 0
    started = time.time()

    with SessionLocal() as db:
        storage = check_storage_root(db, settings.storage_root)
        print(f"storage={storage.root} available={storage.available} message={storage.message}", flush=True)
        if not storage.available:
            raise SystemExit(2)

    files = with_db_retry(count_versions, "count_versions")
    print(f"start files={files} versions={files}", flush=True)

    while files < TARGET_FILES and attempts < MAX_ATTEMPTS:
        sources = with_db_retry(lambda: select_sources(BATCH_SIZE), "select_sources")
        if not sources:
            print("no_more_sources", flush=True)
            break

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_url, item, TIMEOUT_SECONDS): item for item in sources}
            for future in concurrent.futures.as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = DownloadFailure(None, f"访问失败：{exc}")

                source_id = item.id
                attempts += 1
                try:
                    if persist_result(source_id, result, storage.root):
                        success += 1
                    elif isinstance(result, DownloadFailure):
                        failed += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    failed += 1
                    print(f"persist_failed source_id={source_id} error={exc}", flush=True)

                if attempts % 5 == 0:
                    files = with_db_retry(count_versions, "count_versions")
                    elapsed = int(time.time() - started)
                    print(
                        f"partial attempts={attempts} success={success} failed={failed} skipped={skipped} "
                        f"files={files} versions={files} elapsed={elapsed}s",
                        flush=True,
                    )

        files = with_db_retry(count_versions, "count_versions")
        elapsed = int(time.time() - started)
        print(
            f"progress attempts={attempts} success={success} failed={failed} skipped={skipped} "
            f"files={files} versions={files} elapsed={elapsed}s",
            flush=True,
        )

    print(f"done attempts={attempts} success={success} failed={failed} skipped={skipped} files={files}", flush=True)


if __name__ == "__main__":
    main()
