#!/usr/bin/env python3
"""Remove duplicate document versions with the same file hash; keep earliest only."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.storage import check_storage_root  # noqa: E402

BUILD_DUP_TEMP = """
CREATE TEMP TABLE tmp_duplicate_versions ON COMMIT DROP AS
WITH ranked AS (
    SELECT
        id,
        document_id,
        file_hash,
        file_path,
        change_type,
        ROW_NUMBER() OVER (
            PARTITION BY document_id, lower(file_hash)
            ORDER BY id
        ) AS rn,
        FIRST_VALUE(id) OVER (
            PARTITION BY document_id, lower(file_hash)
            ORDER BY id
        ) AS keep_id
    FROM document_versions
    WHERE file_hash IS NOT NULL AND btrim(file_hash) <> ''
)
SELECT id AS delete_id, keep_id, document_id, file_path, change_type
FROM ranked
WHERE rn > 1
"""

SUMMARY_SQL = """
SELECT
    count(*) AS delete_count,
    count(DISTINCT document_id) AS affected_documents
FROM tmp_duplicate_versions
"""

BREAKDOWN_SQL = """
SELECT change_type, count(*)
FROM tmp_duplicate_versions
GROUP BY change_type
ORDER BY count(*) DESC
"""

SAMPLE_SQL = """
SELECT delete_id, keep_id, document_id, change_type
FROM tmp_duplicate_versions
ORDER BY delete_id
LIMIT 10
"""


def safe_delete_file(storage_root: Path, relative_path: str | None) -> bool:
    if not relative_path or relative_path.startswith("baidupan:"):
        return False
    path = Path(relative_path)
    if not path.is_absolute():
        path = storage_root / path
    try:
        resolved = path.resolve()
        root = storage_root.resolve()
        if not str(resolved).lower().startswith(str(root).lower()):
            return False
        if resolved.exists() and resolved.is_file():
            resolved.unlink()
            return True
    except OSError:
        return False
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete duplicate document versions with identical file hash.")
    parser.add_argument("--execute", action="store_true", help="Apply changes (default is dry-run).")
    parser.add_argument("--delete-files", action="store_true", help="Delete local files only referenced by removed versions.")
    args = parser.parse_args()

    settings = get_settings()
    with SessionLocal() as db:
        db.execute(text("SET statement_timeout = 0"))
        db.execute(text(BUILD_DUP_TEMP))
        summary = db.execute(text(SUMMARY_SQL)).one()
        breakdown = db.execute(text(BREAKDOWN_SQL)).all()
        print(f"duplicate_versions_to_delete={summary.delete_count}")
        print(f"affected_documents={summary.affected_documents}")
        print("delete_change_type_breakdown=", {row[0] or "unknown": row[1] for row in breakdown})

        if summary.delete_count == 0:
            print("nothing_to_do")
            db.rollback()
            return 0

        if not args.execute:
            print("dry_run_only; pass --execute to apply")
            for row in db.execute(text(SAMPLE_SQL)).all():
                print(
                    f"  would_delete dv#{row.delete_id} keep dv#{row.keep_id} "
                    f"doc#{row.document_id} change={row.change_type}"
                )
            db.rollback()
            return 0

        repointed = {}
        for table, column in (
            ("standard_file_matches", "document_version_id"),
            ("standard_change_logs", "document_version_id"),
            ("local_file_intake_tasks", "linked_version_id"),
        ):
            result = db.execute(
                text(
                    f"""
                    UPDATE {table} AS t
                    SET {column} = d.keep_id
                    FROM tmp_duplicate_versions d
                    WHERE t.{column} = d.delete_id
                    """
                )
            )
            repointed[table] = result.rowcount

        deleted_files = 0
        if args.delete_files:
            storage = check_storage_root(db, settings.storage_root)
            if storage.available:
                kept_paths = {
                    row[0]
                    for row in db.execute(
                        text(
                            """
                            SELECT DISTINCT dv.file_path
                            FROM document_versions dv
                            JOIN tmp_duplicate_versions d ON d.keep_id = dv.id
                            WHERE dv.file_path IS NOT NULL
                            """
                        )
                    ).all()
                }
                for row in db.execute(text("SELECT file_path FROM tmp_duplicate_versions")).all():
                    file_path = row[0]
                    if file_path and file_path not in kept_paths:
                        if safe_delete_file(storage.root, file_path):
                            deleted_files += 1

        delete_result = db.execute(
            text(
                """
                DELETE FROM document_versions dv
                USING tmp_duplicate_versions d
                WHERE dv.id = d.delete_id
                """
            )
        )
        current_fix = db.execute(
            text(
                """
                WITH latest AS (
                    SELECT d.document_id, max(dv.id) AS version_id
                    FROM tmp_duplicate_versions d
                    JOIN document_versions dv ON dv.document_id = d.document_id
                    GROUP BY d.document_id
                )
                UPDATE document_versions dv
                SET is_current = (dv.id = latest.version_id)
                FROM latest
                WHERE dv.document_id = latest.document_id
                """
            )
        )
        doc_fix = db.execute(
            text(
                """
                WITH latest AS (
                    SELECT d.document_id, max(dv.id) AS version_id
                    FROM tmp_duplicate_versions d
                    JOIN document_versions dv ON dv.document_id = d.document_id
                    GROUP BY d.document_id
                )
                UPDATE documents d
                SET current_version_id = latest.version_id
                FROM latest
                WHERE d.id = latest.document_id
                """
            )
        )
        db.commit()

        print("deleted_versions", delete_result.rowcount)
        print("repointed_foreign_keys", repointed)
        print("document_versions_current_rows_updated", current_fix.rowcount)
        print("documents_current_version_updated", doc_fix.rowcount)
        print("deleted_local_files", deleted_files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
