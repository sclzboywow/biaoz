from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import models  # noqa: E402
from app.baidu_pan_storage import BaiduPanClient, BaiduPanError, load_baidu_pan_config, parse_baidu_pan_uri  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.settings_store import ensure_default_settings  # noqa: E402


def sanitize_error(value: object) -> str:
    text = repr(value)
    text = re.sub(r"access_token=[^&'\"\\s]+", "access_token=<redacted>", text)
    text = re.sub(r"refresh_token=[^&'\"\\s]+", "refresh_token=<redacted>", text)
    return text[:1000]


def call_with_retries(label: str, retries: int, func):
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            return func()
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(5.0, 0.5 * (2**attempt)))
    raise last_error or RuntimeError(f"{label} failed")


def remote_version_ids(
    *,
    limit: int | None,
    current_only: bool,
    version_ids: list[int] | None,
    min_id: int | None,
    latest_first: bool,
) -> list[int]:
    with SessionLocal() as db:
        query = db.query(models.DocumentVersion.id).filter(models.DocumentVersion.file_path.like("baidupan:%"))
        if current_only:
            query = query.filter(models.DocumentVersion.is_current.is_(True))
        if version_ids:
            query = query.filter(models.DocumentVersion.id.in_(version_ids))
        if min_id is not None:
            query = query.filter(models.DocumentVersion.id >= min_id)
        query = query.order_by(models.DocumentVersion.id.desc() if latest_first else models.DocumentVersion.id)
        if limit:
            query = query.limit(limit)
        return [row[0] for row in query.all()]


def verify_one(version_id: int, *, mode: str, retries: int) -> dict:
    with SessionLocal() as db:
        ensure_default_settings(db)
        version = db.get(models.DocumentVersion, version_id)
        if version is None:
            return {"version_id": version_id, "ok": False, "status": "missing_version"}
        if not version.file_path.startswith("baidupan:"):
            return {"version_id": version_id, "ok": False, "status": "not_remote", "file_path": version.file_path}
        config = load_baidu_pan_config(db)
        expected = {
            "file_name": version.file_name,
            "file_size": int(version.file_size or 0),
            "file_hash": version.file_hash,
            "content_hash": version.content_hash,
            "file_path": version.file_path,
        }

    client = BaiduPanClient(config)
    remote_path, fs_id = parse_baidu_pan_uri(expected["file_path"])

    meta = call_with_retries(
        "file_meta_uri",
        retries,
        lambda: client.file_meta_uri(expected["file_path"], dlink=mode == "download"),
    )
    remote_size = int(meta.get("size") or 0)
    remote_meta_path = str(meta.get("path") or "")
    remote_fs_id = str(meta.get("fs_id") or "")
    checks = {
        "size": remote_size == expected["file_size"],
        "path": (not remote_meta_path) or remote_meta_path == remote_path,
        "fs_id": (not fs_id) or remote_fs_id == str(fs_id),
    }

    result = {
        "version_id": version_id,
        "ok": all(checks.values()),
        "status": "verified" if all(checks.values()) else "metadata_mismatch",
        "mode": mode,
        "checks": checks,
        "expected": {
            "size": expected["file_size"],
            "path": remote_path,
            "fs_id": fs_id,
            "sha256": expected["file_hash"],
        },
        "remote": {
            "size": remote_size,
            "path": remote_meta_path,
            "fs_id": remote_fs_id,
            "md5": meta.get("md5"),
            "server_filename": meta.get("server_filename"),
        },
    }

    if mode == "download":
        content, _content_type = call_with_retries(
            "download_uri",
            retries,
            lambda: client.download_uri(expected["file_path"]),
        )
        remote_sha256 = hashlib.sha256(content).hexdigest()
        expected_sha256 = str(expected["file_hash"] or expected["content_hash"] or "").lower()
        result["remote"]["sha256"] = remote_sha256
        result["checks"]["sha256"] = remote_sha256.lower() == expected_sha256
        result["ok"] = all(result["checks"].values())
        result["status"] = "verified" if result["ok"] else "hash_mismatch"
    elif mode != "metadata":
        return {"version_id": version_id, "ok": False, "status": "invalid_mode", "mode": mode}

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify DocumentVersion records archived in Baidu Pan.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--mode", choices=("metadata", "download"), default="metadata")
    parser.add_argument("--all-versions", action="store_true", help="Include non-current versions.")
    parser.add_argument("--version-id", type=int, action="append", help="Verify a specific document version id. Can be repeated.")
    parser.add_argument("--min-id", type=int, help="Only verify versions with id >= this value.")
    parser.add_argument("--latest-first", action="store_true", help="Verify newest remote versions first.")
    parser.add_argument("--retries", type=int, default=3, help="Retry transient HTTP failures per remote check.")
    args = parser.parse_args()

    ids = remote_version_ids(
        limit=args.limit if args.limit > 0 else None,
        current_only=not args.all_versions,
        version_ids=args.version_id,
        min_id=args.min_id,
        latest_first=args.latest_first,
    )
    print(
        "baidu_pan_verify_plan "
        + json.dumps(
            {
                "selected": len(ids),
                "workers": args.workers,
                "mode": args.mode,
                "current_only": not args.all_versions,
                "latest_first": args.latest_first,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if not ids:
        return 0

    ok = 0
    failed = 0
    statuses: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(verify_one, version_id, mode=args.mode, retries=args.retries): version_id
            for version_id in ids
        }
        for future in as_completed(futures):
            version_id = futures[future]
            try:
                result = future.result()
            except BaiduPanError as exc:
                result = {"version_id": version_id, "ok": False, "status": "baidu_pan_error", "error": sanitize_error(exc)}
            except Exception as exc:
                result = {"version_id": version_id, "ok": False, "status": "unexpected_error", "error": sanitize_error(exc)}
            ok += 1 if result.get("ok") else 0
            failed += 0 if result.get("ok") else 1
            status = str(result.get("status") or "unknown")
            statuses[status] = statuses.get(status, 0) + 1
            print("baidu_pan_verify_result " + json.dumps(result, ensure_ascii=False, default=str), flush=True)

    print(
        "baidu_pan_verify_summary "
        + json.dumps({"ok": ok, "failed": failed, "statuses": statuses}, ensure_ascii=False),
        flush=True,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
