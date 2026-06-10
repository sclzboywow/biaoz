from __future__ import annotations

import atexit
import json
import queue
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.baidu_pan_storage import (
    BaiduPanClient,
    BaiduPanError,
    append_baidu_pan_sync_remark,
    build_baidu_pan_sync_payload,
    is_baidu_pan_uri,
    load_baidu_pan_config,
    version_has_baidu_pan,
)
from app.database import SessionLocal
from app.download_service import archive_object_relative_path, configured_storage_backend
from app import models
from app.settings_store import ensure_default_settings

_FAILURE_LOG = Path(__file__).resolve().parents[2] / "logs" / "baidu-upload-failures.jsonl"
_FAILURE_LOG_LOCK = threading.Lock()


@dataclass(frozen=True)
class _UploadJob:
    version_id: int
    file_hash: str
    file_name: str
    content: bytes


def _append_failure_log(payload: dict) -> None:
    _FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with _FAILURE_LOG_LOCK:
        with _FAILURE_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class BaiduUploadQueue:
    def __init__(self, *, workers: int = 4) -> None:
        self._workers = max(workers, 1)
        self._queue: queue.Queue[_UploadJob | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._started = False
        self._lock = threading.Lock()
        self.submitted = 0
        self.completed = 0
        self.failed = 0

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            for index in range(self._workers):
                thread = threading.Thread(target=self._worker, name=f"baidu-upload-{index}", daemon=True)
                thread.start()
                self._threads.append(thread)
            self._started = True

    def submit(self, *, version_id: int, file_hash: str, file_name: str, content: bytes) -> None:
        self.start()
        self.submitted += 1
        self._queue.put(_UploadJob(version_id=version_id, file_hash=file_hash, file_name=file_name, content=content))

    def flush(self, timeout: float | None = None) -> dict[str, int]:
        self.start()
        self._queue.join()
        return {"submitted": self.submitted, "completed": self.completed, "failed": self.failed}

    def shutdown(self) -> None:
        for _ in self._threads:
            self._queue.put(None)
        for thread in self._threads:
            thread.join(timeout=5)

    def _worker(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                self._process(job)
            finally:
                self._queue.task_done()

    def _process(self, job: _UploadJob) -> None:
        with SessionLocal() as db:
            ensure_default_settings(db)
            version = db.get(models.DocumentVersion, job.version_id)
            if version is None:
                self.failed += 1
                _append_failure_log(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "version_id": job.version_id,
                        "file_hash": job.file_hash,
                        "file_name": job.file_name,
                        "status": "missing_version",
                    }
                )
                return
            if version_has_baidu_pan(file_path=version.file_path, remark=version.remark):
                self.completed += 1
                return

            storage_backend = configured_storage_backend(db)
            local_path = version.file_path
            try:
                remote_relative_path = archive_object_relative_path(job.file_hash, job.file_name)
                remote_result = BaiduPanClient(load_baidu_pan_config(db)).upload_bytes(job.content, remote_relative_path)
                sync_payload = build_baidu_pan_sync_payload(
                    remote_result=remote_result,
                    file_hash=job.file_hash,
                    source="async_upload",
                )
                if storage_backend == "dual" and local_path and not is_baidu_pan_uri(local_path):
                    version.remark = append_baidu_pan_sync_remark(version.remark, sync_payload)
                else:
                    version.file_path = remote_result.uri
                    version.remark = append_baidu_pan_sync_remark(version.remark, sync_payload)
                db.commit()
                self.completed += 1
            except BaiduPanError as exc:
                db.rollback()
                failure_payload = {
                    "status": "failed",
                    "synced_at": datetime.now(UTC).isoformat(),
                    "sha256": job.file_hash,
                    "source": "async_upload",
                    "error": str(exc)[:1000],
                }
                version = db.get(models.DocumentVersion, job.version_id)
                if version is not None:
                    version.remark = append_baidu_pan_sync_remark(version.remark, failure_payload)
                    db.commit()
                self.failed += 1
                _append_failure_log(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "version_id": job.version_id,
                        "file_hash": job.file_hash,
                        "file_name": job.file_name,
                        "local_file_path": local_path,
                        "storage_backend": storage_backend,
                        "status": "upload_failed",
                        "error": str(exc)[:1000],
                    }
                )


_QUEUE: BaiduUploadQueue | None = None
_QUEUE_LOCK = threading.Lock()


def get_baidu_upload_queue(*, workers: int = 4) -> BaiduUploadQueue:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is None:
            _QUEUE = BaiduUploadQueue(workers=workers)
            atexit.register(lambda: _QUEUE.shutdown() if _QUEUE else None)
        return _QUEUE


def reset_baidu_upload_queue() -> None:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is not None:
            _QUEUE.shutdown()
        _QUEUE = None


def flush_baidu_upload_queue() -> dict[str, int]:
    with _QUEUE_LOCK:
        if _QUEUE is None:
            return {"submitted": 0, "completed": 0, "failed": 0}
        return _QUEUE.flush()
