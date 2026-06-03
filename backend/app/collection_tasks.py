from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.settings_store import get_int_setting
from app.url_checker import check_url_source


def normalize_collection_batch_size(value: int | None, default: int = 50) -> int:
    return min(max(value or default, 1), 500)


def stream_url_source_ids(db: Session, include_manual: bool, batch_size: int, start_after_id: int = 0):
    last_id = start_after_id
    size = normalize_collection_batch_size(batch_size)
    while True:
        statement = select(models.UrlSource.id).where(models.UrlSource.id > last_id)
        if not include_manual:
            statement = statement.where(models.UrlSource.check_frequency != "manual")
        ids = list(db.scalars(statement.order_by(models.UrlSource.id).limit(size)))
        if not ids:
            break
        yield ids
        last_id = ids[-1]


def run_url_check_task(
    task_id: int,
    include_manual: bool | None = None,
    batch_size: int | None = None,
    worker_id: str | None = None,
) -> None:
    settings = get_settings()
    normalized_worker_id = worker_id or f"worker-{os.getpid()}"
    with SessionLocal() as db:
        task = db.get(models.CollectionTask, task_id)
        if task is None or task.status == "finished":
            return

        resolved_include_manual = bool(task.include_manual if include_manual is None else include_manual)
        resolved_batch_size = normalize_collection_batch_size(batch_size or task.batch_size)
        task.status = "running"
        task.started_at = task.started_at or datetime.now(UTC)
        task.include_manual = resolved_include_manual
        task.batch_size = resolved_batch_size
        task.worker_id = normalized_worker_id
        task.heartbeat_at = datetime.now(UTC)
        timeout_seconds = get_int_setting(db, "download_timeout_seconds", 30)
        count_statement = select(func.count(models.UrlSource.id))
        if not resolved_include_manual:
            count_statement = count_statement.where(models.UrlSource.check_frequency != "manual")
        task.total = db.scalar(count_statement) or 0
        db.commit()

        try:
            for source_ids in stream_url_source_ids(
                db,
                resolved_include_manual,
                resolved_batch_size,
                task.last_source_id or 0,
            ):
                for source_id in source_ids:
                    source = db.get(models.UrlSource, source_id)
                    if source is None:
                        continue
                    result = check_url_source(db, source, settings.storage_root, timeout_seconds)
                    task = db.get(models.CollectionTask, task_id)
                    if task is None:
                        return
                    task.processed += 1
                    if result.ok:
                        task.success += 1
                    else:
                        task.failed += 1
                    task.last_source_id = source_id
                    task.heartbeat_at = datetime.now(UTC)
                    task.updated_at = datetime.now(UTC)
                    db.commit()

            task = db.get(models.CollectionTask, task_id)
            if task:
                task.status = "finished"
                task.finished_at = datetime.now(UTC)
                task.message = "Batch URL check finished."
                db.commit()
        except Exception as exc:  # pragma: no cover - background task safety net
            task = db.get(models.CollectionTask, task_id)
            if task:
                task.status = "failed"
                task.finished_at = datetime.now(UTC)
                task.message = str(exc)
                db.commit()


def claim_next_pending_url_check_task(worker_id: str) -> int | None:
    with SessionLocal() as db:
        statement = (
            select(models.CollectionTask)
            .where(
                models.CollectionTask.task_type == "url_check",
                models.CollectionTask.status == "pending",
            )
            .order_by(models.CollectionTask.id)
            .with_for_update(skip_locked=True)
        )
        task = db.scalars(statement).first()
        if task is None:
            return None
        task.status = "running"
        task.worker_id = worker_id
        task.started_at = task.started_at or datetime.now(UTC)
        task.heartbeat_at = datetime.now(UTC)
        task.message = "Claimed by collection worker."
        db.commit()
        return task.id


def run_pending_url_check_tasks(max_tasks: int = 0, poll_seconds: float = 5.0, worker_id: str | None = None) -> int:
    resolved_worker_id = worker_id or f"collection-worker-{os.getpid()}"
    processed = 0

    while True:
        task_id = claim_next_pending_url_check_task(resolved_worker_id)
        if task_id is None:
            if max_tasks and processed >= max_tasks:
                return processed
            if max_tasks == 1:
                return processed
            time.sleep(poll_seconds)
            continue

        run_url_check_task(task_id, worker_id=resolved_worker_id)
        processed += 1
        if max_tasks and processed >= max_tasks:
            return processed
