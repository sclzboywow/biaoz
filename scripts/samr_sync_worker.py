from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func

from app.database import SessionLocal
from app.models import SourceCategory, StandardDetail, StandardResource, TrustedSource
from app.samr_std_sync import sync_samr_std_resources


RATE_LIMIT_TOKENS = ("访问过于频繁", "401", "Unauthorized")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _log(message: str) -> None:
    print(f"[{_now()}] {message}", flush=True)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception:
        return False
    return f'"{pid}"' in completed.stdout or f",{pid}," in completed.stdout


def _claim_pidfile(pidfile: Path) -> None:
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    if pidfile.exists():
        try:
            existing_pid = int(pidfile.read_text(encoding="utf-8").strip())
        except Exception:
            existing_pid = 0
        if _pid_running(existing_pid):
            raise SystemExit(f"SAMR sync worker is already running: pid={existing_pid}")
    pidfile.write_text(str(os.getpid()), encoding="utf-8")


def _release_pidfile(pidfile: Path) -> None:
    try:
        if pidfile.exists() and pidfile.read_text(encoding="utf-8").strip() == str(os.getpid()):
            pidfile.unlink()
    except Exception:
        pass


def _snapshot(db) -> dict[str, int | str | bool | None]:
    source = db.query(TrustedSource).filter(TrustedSource.adapter_key == "samr_std_public").first()
    if source is None:
        raise RuntimeError("samr_std_public trusted source does not exist")
    category = (
        db.query(SourceCategory)
        .filter(SourceCategory.source_id == source.id, SourceCategory.source_category_id == "gb")
        .first()
    )
    if category is None:
        raise RuntimeError("SAMR GB source category does not exist")

    resources = db.query(func.count(StandardResource.id)).filter(StandardResource.source_id == source.id).scalar()
    details = (
        db.query(func.count(StandardDetail.id))
        .join(StandardResource, StandardDetail.standard_resource_id == StandardResource.id)
        .filter(StandardResource.source_id == source.id)
        .scalar()
    )
    online_links = (
        db.query(func.count(StandardResource.id))
        .filter(
            StandardResource.source_id == source.id,
            StandardResource.pdf_trial_url.isnot(None),
            StandardResource.pdf_trial_url != "",
        )
        .scalar()
    )
    total_pages = max(1, ((category.resource_count or 0) + 20 - 1) // 20)
    return {
        "source_id": source.id,
        "page": category.last_synced_page or 0,
        "status": category.sync_status,
        "error": category.last_sync_error,
        "finished_at": category.last_sync_finished_at.isoformat() if category.last_sync_finished_at else None,
        "remote_total": category.resource_count or 0,
        "total_pages": total_pages,
        "resources": resources or 0,
        "details": details or 0,
        "online_links": online_links or 0,
        "completed": (category.last_synced_page or 0) >= total_pages,
    }


def _cooldown_active(snapshot: dict[str, int | str | bool | None], cooldown_seconds: int) -> bool:
    error = str(snapshot.get("error") or "")
    if not any(token in error for token in RATE_LIMIT_TOKENS):
        return False
    with SessionLocal() as db:
        source = db.query(TrustedSource).filter(TrustedSource.adapter_key == "samr_std_public").first()
        category = (
            db.query(SourceCategory)
            .filter(SourceCategory.source_id == source.id, SourceCategory.source_category_id == "gb")
            .first()
        )
        finished = _as_utc(category.last_sync_finished_at) or _as_utc(category.last_sync_started_at)
    return bool(finished and (datetime.now(UTC) - finished).total_seconds() < cooldown_seconds)


def run_worker(args: argparse.Namespace) -> int:
    pidfile = Path(args.pid_file)
    _claim_pidfile(pidfile)
    pages_done = 0
    try:
        _log(
            "SAMR worker started "
            f"interval={args.interval_seconds}s request_delay={os.getenv('SAMR_REQUEST_DELAY_SECONDS')}s "
            f"cooldown={os.getenv('SAMR_RATE_LIMIT_COOLDOWN_SECONDS')}s"
        )
        while True:
            with SessionLocal() as db:
                snap = _snapshot(db)
            _log("snapshot " + json.dumps(snap, ensure_ascii=False, default=str))

            if snap["completed"]:
                _log("all pages completed; worker exiting")
                return 0
            if snap["status"] == "同步中":
                _log("previous sync is still marked running; skip this cycle")
            elif _cooldown_active(snap, args.cooldown_seconds):
                _log(f"rate-limit cooldown active after error={snap['error']!r}; skip this cycle")
            else:
                with SessionLocal() as db:
                    source = db.query(TrustedSource).filter(TrustedSource.adapter_key == "samr_std_public").first()
                    result = sync_samr_std_resources(
                        db,
                        source_id=source.id,
                        max_pages=1,
                        include_detail=True,
                        only_pending_categories=True,
                    )
                    after = _snapshot(db)
                pages_done += int(result.get("pages", 0))
                _log(
                    "sync_result "
                    + json.dumps(
                        {
                            "result": result,
                            "after_page": after["page"],
                            "after_status": after["status"],
                            "after_error": after["error"],
                            "resources": after["resources"],
                            "details": after["details"],
                            "online_links": after["online_links"],
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )
                if any(token in str(after["error"] or "") for token in RATE_LIMIT_TOKENS):
                    _log("access limit detected; worker will wait for cooldown before next request")

            if args.once or (args.max_pages and pages_done >= args.max_pages):
                _log("requested page limit reached; worker exiting")
                return 0
            time.sleep(args.interval_seconds)
    finally:
        _release_pidfile(pidfile)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Slow SAMR trusted-source metadata/link sync worker.")
    parser.add_argument("--once", action="store_true", help="Run one eligible page and exit.")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum synced pages before exit; 0 means unlimited.")
    parser.add_argument("--interval-seconds", type=int, default=120, help="Delay between page sync attempts.")
    parser.add_argument("--cooldown-seconds", type=int, default=1800, help="Cooldown after 401/access-frequency errors.")
    parser.add_argument(
        "--pid-file",
        default=str(Path(__file__).resolve().parents[1] / "logs" / "samr-sync-worker.pid"),
        help="PID file path used to avoid duplicate workers.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run_worker(parse_args()))
    except KeyboardInterrupt:
        _log("worker interrupted")
        raise SystemExit(130)
    except Exception as exc:
        _log(f"worker failed: {exc}")
        raise
