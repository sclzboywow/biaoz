from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import models  # noqa: E402
from app.baidu_pan_storage import (
    BaiduPanClient,
    BaiduPanError,
    append_baidu_pan_sync_remark,
    build_baidu_pan_sync_payload,
    is_baidu_pan_uri,
    load_baidu_pan_config,
    version_has_baidu_pan,
)  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.download_service import archive_object_relative_path, configured_storage_backend  # noqa: E402
from app.settings_store import ensure_default_settings, get_setting  # noqa: E402
from app.storage import configured_storage_root  # noqa: E402
from sqlalchemy import or_  # noqa: E402


def sanitize_error(value: object) -> str:
    text = repr(value)
    text = re.sub(r"access_token=[^&'\"\\s]+", "access_token=<redacted>", text)
    text = re.sub(r"refresh_token=[^&'\"\\s]+", "refresh_token=<redacted>", text)
    return text[:1000]


def resolve_local_file(db, raw_file_path: str) -> Path | None:
    raw_path = Path(raw_file_path)
    roots = [configured_storage_root(db, get_settings().storage_root)]
    fallback_roots = get_setting(db, "storage_fallback_roots", "") or ""
    for item in fallback_roots.split(";"):
        item = item.strip()
        if item:
            roots.append(Path(item).expanduser().resolve())

    candidates: list[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.extend(root / raw_path for root in roots)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def pending_version_ids(limit: int | None, current_only: bool, version_ids: list[int] | None = None) -> list[int]:
    with SessionLocal() as db:
        query = db.query(models.DocumentVersion.id, models.DocumentVersion.file_path, models.DocumentVersion.remark)
        if version_ids:
            query = query.filter(models.DocumentVersion.id.in_(version_ids))
        if current_only:
            query = query.filter(models.DocumentVersion.is_current.is_(True))
        query = query.filter(~models.DocumentVersion.file_path.like("baidupan:%"))
        # Prefer rows that still lack a successful baidu_pan_sync remote_uri marker.
        query = query.filter(
            or_(
                models.DocumentVersion.remark.is_(None),
                ~models.DocumentVersion.remark.like("%remote_uri%baidupan:%"),
            )
        )
        query = query.order_by(models.DocumentVersion.id.asc())
        if limit:
            query = query.limit(limit * 3)
        pending: list[int] = []
        for version_id, file_path, remark in query.all():
            if version_has_baidu_pan(file_path=file_path, remark=remark):
                continue
            pending.append(version_id)
            if limit and len(pending) >= limit:
                break
        return pending


def append_sync_remark(existing: str | None, payload: dict) -> str:
    line = "baidu_pan_sync=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (existing.rstrip() + "\n" + line) if existing else line


def sync_one(version_id: int, *, verify_mode: str, update_db: bool) -> dict:
    with SessionLocal() as db:
        ensure_default_settings(db)
        version = db.get(models.DocumentVersion, version_id)
        if version is None:
            return {"version_id": version_id, "ok": False, "status": "missing_version"}
        if version_has_baidu_pan(file_path=version.file_path, remark=version.remark):
            return {"version_id": version_id, "ok": True, "status": "already_remote"}
        local_path = resolve_local_file(db, version.file_path)
        if local_path is None:
            return {"version_id": version_id, "ok": False, "status": "local_missing", "file_path": version.file_path}
        content = local_path.read_bytes()
        file_hash = hashlib.sha256(content).hexdigest()
        local_md5 = hashlib.md5(content).hexdigest()
        local_size = len(content)
        if version.file_hash and file_hash.lower() != version.file_hash.lower():
            return {
                "version_id": version_id,
                "ok": False,
                "status": "local_hash_mismatch",
                "db_hash": version.file_hash,
                "local_hash": file_hash,
                "file_path": str(local_path),
            }
        file_name = version.file_name
        original_file_path = version.file_path
        config = load_baidu_pan_config(db)

    client = BaiduPanClient(config)
    remote_relative_path = archive_object_relative_path(file_hash, file_name)
    started = time.time()
    remote = client.upload_bytes(content, remote_relative_path)
    remote_uri = remote.uri

    verification: dict = {"mode": verify_mode}
    if verify_mode == "download":
        remote_content, _content_type = client.download_uri(remote_uri)
        remote_sha256 = hashlib.sha256(remote_content).hexdigest()
        verification.update({"sha256": remote_sha256})
        if remote_sha256.lower() != file_hash.lower():
            return {
                "version_id": version_id,
                "ok": False,
                "status": "remote_hash_mismatch",
                "local_hash": file_hash,
                "remote_hash": remote_sha256,
                "remote_uri": remote_uri,
            }
    elif verify_mode == "metadata":
        meta = client.file_meta_uri(remote_uri)
        remote_md5 = str(meta.get("md5") or "").lower()
        remote_size = int(meta.get("size") or 0)
        verification.update({"md5": remote_md5, "size": remote_size, "path": meta.get("path")})
        if remote_size != local_size:
            return {
                "version_id": version_id,
                "ok": False,
                "status": "remote_metadata_mismatch",
                "local_md5": local_md5,
                "remote_md5": remote_md5,
                "local_size": local_size,
                "remote_size": remote_size,
                "remote_uri": remote_uri,
            }
        verification["content_md5_sent"] = local_md5
        verification["remote_md5_is_content_md5"] = remote_md5 == local_md5.lower()
    elif verify_mode != "none":
        return {"version_id": version_id, "ok": False, "status": "invalid_verify_mode", "verify_mode": verify_mode}

    if update_db:
        with SessionLocal() as db:
            ensure_default_settings(db)
            version = db.get(models.DocumentVersion, version_id)
            if version is None:
                return {"version_id": version_id, "ok": False, "status": "missing_on_update", "remote_uri": remote_uri}
            if version_has_baidu_pan(file_path=version.file_path, remark=version.remark):
                return {"version_id": version_id, "ok": True, "status": "already_remote", "remote_uri": remote_uri}
            storage_backend = configured_storage_backend(db)
            sync_payload = build_baidu_pan_sync_payload(
                remote_result=remote,
                file_hash=file_hash,
                source="backfill_sync",
            )
            sync_payload.update(
                {
                    "verified_at": datetime.now(UTC).isoformat(),
                    "original_file_path": original_file_path,
                    "md5": local_md5,
                    "verify_mode": verify_mode,
                    "verification": verification,
                }
            )
            version.file_hash = file_hash
            version.content_hash = file_hash
            if storage_backend == "dual" and original_file_path and not is_baidu_pan_uri(original_file_path):
                version.remark = append_baidu_pan_sync_remark(version.remark, sync_payload)
            else:
                version.file_path = remote_uri
                version.remark = append_baidu_pan_sync_remark(version.remark, sync_payload)
            db.commit()

    return {
        "version_id": version_id,
        "ok": True,
        "status": "synced",
        "bytes": local_size,
        "sha256": file_hash,
        "md5": local_md5,
        "remote_uri": remote_uri,
        "verification": verification,
        "elapsed_ms": round((time.time() - started) * 1000),
        "updated_db": update_db,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload existing local document versions to Baidu Pan and verify by hash.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--no-update-db", action="store_true", help="Upload and verify, but keep DocumentVersion.file_path unchanged.")
    parser.add_argument("--verify-mode", choices=("metadata", "download", "none"), default="metadata", help="Verification mode after upload. metadata sends content-md5 during upload and confirms remote size/path; download compares SHA-256 by reading back the object.")
    parser.add_argument("--no-download-verify", action="store_true", help="Deprecated compatibility flag; metadata verification is the default.")
    parser.add_argument("--no-verify", action="store_true", help="Skip remote verification after upload.")
    parser.add_argument("--all-versions", action="store_true", help="Include non-current versions.")
    parser.add_argument("--version-id", type=int, action="append", help="Sync a specific document version id. Can be repeated.")
    args = parser.parse_args()
    verify_mode = "none" if args.no_verify else args.verify_mode

    ids = pending_version_ids(args.limit if args.limit > 0 else None, current_only=not args.all_versions, version_ids=args.version_id)
    print(
        "baidu_pan_sync_plan "
        + json.dumps(
            {
                "pending_selected": len(ids),
                "workers": args.workers,
                "update_db": not args.no_update_db,
                "verify_mode": verify_mode,
                "current_only": not args.all_versions,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if not ids:
        return 0

    ok = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(
                sync_one,
                version_id,
                verify_mode=verify_mode,
                update_db=not args.no_update_db,
            ): version_id
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
            print("baidu_pan_sync_result " + json.dumps(result, ensure_ascii=False, default=str), flush=True)

    print("baidu_pan_sync_summary " + json.dumps({"ok": ok, "failed": failed}, ensure_ascii=False), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
