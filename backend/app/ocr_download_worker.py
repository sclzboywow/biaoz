"""OCR 下载后台 worker：独立进程轮询并执行受控下载任务。"""

from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path

from app.config import get_settings
from app.database import SessionLocal
from app.ocr_download_service import claim_next_ocr_task, run_ocr_download_task
from app.settings_store import ensure_default_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR controlled download worker")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--once", action="store_true", help="Process at most one task then exit")
    args = parser.parse_args()

    worker_id = args.worker_id or f"ocr-worker-{uuid.uuid4().hex[:8]}"
    settings = get_settings()
    storage_root = Path(settings.storage_root)

    while True:
        with SessionLocal() as db:
            ensure_default_settings(db)
            task = claim_next_ocr_task(db, worker_id)
            if task is None:
                if args.once:
                    return 0
                time.sleep(max(1, args.poll_seconds))
                continue
            result = run_ocr_download_task(db, task.id, storage_root=storage_root)
            print(f"task_id={task.id} status={result.get('status')} ok={result.get('ok')}")
            if args.once:
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
