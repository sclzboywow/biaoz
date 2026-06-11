"""Compare DB fingerprints across host scripts, Docker API, and worker activity."""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import create_engine, func, select, text

from app import models
from app.config import get_settings
from app.database import SessionLocal


def fingerprint(db) -> dict:
    return {
        "url_sources": db.scalar(select(func.count()).select_from(models.UrlSource)) or 0,
        "documents": db.scalar(select(func.count()).select_from(models.Document)) or 0,
        "standard_resources": db.scalar(select(func.count()).select_from(models.StandardResource)) or 0,
        "file_objects": db.scalar(select(func.count()).select_from(models.FileObject)) or 0,
        "governance_decisions": db.scalar(select(func.count()).select_from(models.GovernanceDecision)) or 0,
    }


def recent_activity(db, minutes: int = 30) -> dict:
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    return {
        f"document_versions_last_{minutes}m": db.scalar(
            select(func.count())
            .select_from(models.DocumentVersion)
            .where(models.DocumentVersion.downloaded_at >= since)
        )
        or 0,
        f"check_logs_last_{minutes}m": db.scalar(
            select(func.count()).select_from(models.CheckLog).where(models.CheckLog.checked_at >= since)
        )
        or 0,
        f"ocr_tasks_finished_last_{minutes}m": db.scalar(
            select(func.count())
            .select_from(models.OcrDownloadTask)
            .where(models.OcrDownloadTask.finished_at >= since)
        )
        or 0,
        "latest_document_version_at": db.scalar(select(func.max(models.DocumentVersion.downloaded_at))),
        "latest_check_log_at": db.scalar(select(func.max(models.CheckLog.checked_at))),
    }


def main() -> int:
    settings = get_settings()
    host_url = settings.database_url
    # Redact password for display
    safe_url = host_url
    if "@" in safe_url and "://" in safe_url:
        prefix, rest = safe_url.split("://", 1)
        if "@" in rest:
            creds, hostpart = rest.split("@", 1)
            user = creds.split(":", 1)[0] if ":" in creds else creds
            safe_url = f"{prefix}://{user}:***@{hostpart}"

    print("=== 数据库连接指纹 ===")
    print(f"host_scripts DATABASE_URL: {safe_url}")

    with SessionLocal() as db:
        fp = fingerprint(db)
        act = recent_activity(db, 30)
        print("\n--- 宿主机脚本库 (backend/.env) ---")
        for k, v in fp.items():
            print(f"  {k}: {v}")
        print("\n--- 近 30 分钟写入活动 ---")
        for k, v in act.items():
            print(f"  {k}: {v}")

        spc_recent = db.scalar(
            text(
                """
                SELECT count(*) FROM document_versions dv
                JOIN url_sources us ON us.id = dv.url_source_id
                WHERE us.url LIKE 'spc-online-reading://%'
                  AND dv.downloaded_at >= NOW() - INTERVAL '30 minutes'
                """
            )
        )
        print(f"  spc_versions_last_30m: {spc_recent}")

    docker_url = os.environ.get("DOCKER_DATABASE_URL")
    if docker_url:
        eng = create_engine(docker_url, pool_pre_ping=True)
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM url_sources) AS url_sources, "
                    "(SELECT count(*) FROM documents) AS documents, "
                    "(SELECT count(*) FROM standard_resources) AS standard_resources"
                )
            ).one()
            print("\n--- Docker API 库 ---")
            print(f"  url_sources: {rows.url_sources}")
            print(f"  documents: {rows.documents}")
            print(f"  standard_resources: {rows.standard_resources}")
            match = rows.url_sources == fp["url_sources"]
            print(f"  MATCH host: {'YES' if match else 'NO'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
