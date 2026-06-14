#!/usr/bin/env python3
"""Batch-delete duplicate document versions (same document_id + file_hash), keep earliest."""
from __future__ import annotations

import sys
import time

import psycopg

DSN = "postgresql://biaoz:biaoz@localhost:5432/biaoz"
BATCH_SIZE = 500

COUNT_SQL = """
SELECT count(*)
FROM document_versions dv
WHERE EXISTS (
    SELECT 1 FROM document_versions earlier
    WHERE earlier.document_id = dv.document_id
      AND lower(earlier.file_hash) = lower(dv.file_hash)
      AND earlier.id < dv.id
)
"""

DELETE_BATCH_SQL = """
WITH doomed AS (
    SELECT dv.id
    FROM document_versions dv
    WHERE EXISTS (
        SELECT 1 FROM document_versions earlier
        WHERE earlier.document_id = dv.document_id
          AND lower(earlier.file_hash) = lower(dv.file_hash)
          AND earlier.id < dv.id
    )
    ORDER BY dv.id
    LIMIT %s
)
DELETE FROM document_versions dv
USING doomed d
WHERE dv.id = d.id
"""

FIX_CURRENT_SQL = """
UPDATE document_versions dv
SET is_current = (dv.id = latest.version_id)
FROM (
    SELECT document_id, max(id) AS version_id
    FROM document_versions
    GROUP BY document_id
) latest
WHERE dv.document_id = latest.document_id
"""

FIX_DOCUMENTS_SQL = """
UPDATE documents d
SET current_version_id = latest.version_id
FROM (
    SELECT document_id, max(id) AS version_id
    FROM document_versions
    GROUP BY document_id
) latest
WHERE d.id = latest.document_id
"""


def main() -> int:
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
            cur.execute(COUNT_SQL)
            remaining = int(cur.fetchone()[0])
            print(f"duplicate_rows_to_remove={remaining}", flush=True)
            if remaining == 0:
                print("nothing_to_do", flush=True)
                return 0

            total_deleted = 0
            batch = 0
            started = time.time()
            while True:
                batch += 1
                cur.execute(DELETE_BATCH_SQL, (BATCH_SIZE,))
                deleted = cur.rowcount
                conn.commit()
                total_deleted += deleted
                print(f"batch={batch} deleted={deleted} total={total_deleted}", flush=True)
                if deleted == 0:
                    break

            cur.execute(FIX_CURRENT_SQL)
            current_rows = cur.rowcount
            cur.execute(FIX_DOCUMENTS_SQL)
            doc_rows = cur.rowcount
            cur.execute(COUNT_SQL)
            remaining_after = int(cur.fetchone()[0])
            conn.commit()

            elapsed = time.time() - started
            print(f"deleted_total={total_deleted}", flush=True)
            print(f"current_rows_updated={current_rows}", flush=True)
            print(f"documents_updated={doc_rows}", flush=True)
            print(f"remaining_duplicates={remaining_after}", flush=True)
            print(f"elapsed_seconds={elapsed:.1f}", flush=True)
    return 0 if remaining_after == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
