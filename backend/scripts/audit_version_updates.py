#!/usr/bin/env python3
"""Audit document version 'updated' rows vs actual file hash changes."""
from __future__ import annotations

import psycopg

DSN = "postgresql://biaoz:biaoz@localhost:5432/biaoz"


def main() -> None:
    with psycopg.connect(DSN) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT change_type, count(*)
            FROM document_versions
            GROUP BY 1
            ORDER BY 2 DESC
            """
        )
        print("=== change_type counts ===")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]}")

        cur.execute(
            """
            WITH ordered AS (
                SELECT
                    dv.id,
                    dv.document_id,
                    dv.change_type,
                    dv.file_hash,
                    dv.file_name,
                    dv.file_size,
                    dv.is_current,
                    dv.created_at,
                    LAG(dv.file_hash) OVER (
                        PARTITION BY dv.document_id ORDER BY dv.id
                    ) AS prev_hash,
                    LAG(dv.id) OVER (
                        PARTITION BY dv.document_id ORDER BY dv.id
                    ) AS prev_id
                FROM document_versions dv
            )
            SELECT count(*)
            FROM ordered
            WHERE change_type = '更新'
              AND prev_hash IS NOT NULL
              AND prev_hash = file_hash
            """
        )
        false_updated = cur.fetchone()[0]
        print(f"\n=== updated but same hash as previous version: {false_updated} ===")

        cur.execute(
            """
            WITH ordered AS (
                SELECT
                    dv.id,
                    dv.document_id,
                    dv.change_type,
                    dv.file_hash,
                    dv.file_name,
                    dv.prev_hash,
                    d.standard_no
                FROM (
                    SELECT
                        dv.*,
                        LAG(dv.file_hash) OVER (
                            PARTITION BY dv.document_id ORDER BY dv.id
                        ) AS prev_hash
                    FROM document_versions dv
                ) dv
                JOIN documents d ON d.id = dv.document_id
            )
            SELECT id, document_id, standard_no, file_name, file_hash
            FROM ordered
            WHERE change_type = '更新'
              AND prev_hash IS NOT NULL
              AND prev_hash = file_hash
            ORDER BY id DESC
            LIMIT 15
            """
        )
        rows = cur.fetchall()
        if rows:
            print("samples:")
            for r in rows:
                print(f"  dv#{r[0]} doc#{r[1]} {r[2]} {r[3]} hash={r[4][:16]}...")

        cur.execute(
            """
            WITH ordered AS (
                SELECT
                    dv.id,
                    dv.document_id,
                    dv.change_type,
                    dv.file_hash,
                    LAG(dv.file_hash) OVER (
                        PARTITION BY dv.document_id ORDER BY dv.id
                    ) AS prev_hash
                FROM document_versions dv
            )
            SELECT count(*)
            FROM ordered
            WHERE change_type = '更新'
              AND prev_hash IS NOT NULL
              AND prev_hash <> file_hash
            """
        )
        true_updated = cur.fetchone()[0]
        print(f"\n=== updated with different hash (likely real): {true_updated} ===")

        cur.execute(
            """
            SELECT count(*)
            FROM document_versions
            WHERE change_type = '更新' AND (
                SELECT count(*)
                FROM document_versions dv2
                WHERE dv2.document_id = document_versions.document_id
            ) = 1
            """
        )
        print(f"=== updated as only version on document (suspicious): {cur.fetchone()[0]} ===")

        cur.execute(
            """
            SELECT count(*)
            FROM document_versions dv
            WHERE change_type = '新增'
              AND EXISTS (
                SELECT 1 FROM document_versions dv2
                WHERE dv2.document_id = dv.document_id AND dv2.id < dv.id
              )
            """
        )
        print(f"=== created but not first version (mislabeled): {cur.fetchone()[0]} ===")

        cur.execute(
            """
            SELECT dv.change_type, left(coalesce(dv.remark,''), 40), count(*)
            FROM document_versions dv
            WHERE dv.remark LIKE '%baidu_pan_sync=%'
            GROUP BY 1, 2
            ORDER BY 3 DESC
            LIMIT 8
            """
        )
        print("\n=== baidu sync remark patterns ===")
        for r in cur.fetchall():
            print(f"  {r[0]} remark={r[1]!r} count={r[2]}")


if __name__ == "__main__":
    main()
