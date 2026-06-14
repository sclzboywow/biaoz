#!/usr/bin/env python3
"""Deep dive into false-positive version updates (same hash)."""
from __future__ import annotations

import psycopg

DSN = "postgresql://biaoz:biaoz@localhost:5432/biaoz"


def main() -> None:
    with psycopg.connect(DSN) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            WITH ordered AS (
                SELECT
                    dv.id,
                    dv.document_id,
                    dv.url_source_id,
                    dv.file_hash,
                    dv.file_name,
                    dv.file_path,
                    dv.remark,
                    dv.created_at,
                    LAG(dv.id) OVER (PARTITION BY dv.document_id ORDER BY dv.id) AS prev_id,
                    LAG(dv.file_hash) OVER (PARTITION BY dv.document_id ORDER BY dv.id) AS prev_hash,
                    LAG(dv.file_path) OVER (PARTITION BY dv.document_id ORDER BY dv.id) AS prev_path,
                    LAG(dv.url_source_id) OVER (PARTITION BY dv.document_id ORDER BY dv.id) AS prev_source_id
                FROM document_versions dv
                WHERE dv.change_type = '更新'
            )
            SELECT
                CASE
                    WHEN prev_hash = file_hash AND coalesce(file_path,'') <> coalesce(prev_path,'') THEN 'same_hash_path_changed'
                    WHEN prev_hash = file_hash AND url_source_id IS DISTINCT FROM prev_source_id THEN 'same_hash_source_changed'
                    WHEN prev_hash = file_hash THEN 'same_hash_other'
                    ELSE 'hash_changed'
                END AS bucket,
                count(*)
            FROM ordered
            WHERE prev_hash IS NOT NULL
            GROUP BY 1
            ORDER BY 2 DESC
            """
        )
        print("=== update buckets ===")
        for bucket, count in cur.fetchall():
            print(f"  {bucket}: {count}")

        cur.execute(
            """
            WITH false_updates AS (
                SELECT dv.id, dv.document_id, dv.url_source_id, dv.file_path, dv.remark,
                       LAG(dv.file_path) OVER (PARTITION BY dv.document_id ORDER BY dv.id) AS prev_path,
                       LAG(dv.url_source_id) OVER (PARTITION BY dv.document_id ORDER BY dv.id) AS prev_source_id
                FROM document_versions dv
                WHERE dv.change_type = '更新'
            )
            SELECT
                CASE
                    WHEN file_path LIKE 'baidupan:%' AND prev_path NOT LIKE 'baidupan:%' THEN 'local_to_baidu'
                    WHEN file_path NOT LIKE 'baidupan:%' AND prev_path LIKE 'baidupan:%' THEN 'baidu_to_local'
                    WHEN file_path LIKE 'baidupan:%' AND prev_path LIKE 'baidupan:%' THEN 'baidu_to_baidu'
                    WHEN remark LIKE '%baidu_pan_sync=%' THEN 'has_baidu_remark'
                    ELSE 'path_other'
                END AS path_bucket,
                count(*)
            FROM false_updates fu
            JOIN document_versions dv ON dv.id = fu.id
            JOIN document_versions pv ON pv.id = (
                SELECT max(dv2.id) FROM document_versions dv2
                WHERE dv2.document_id = fu.document_id AND dv2.id < fu.id
            )
            WHERE dv.file_hash = pv.file_hash
            GROUP BY 1
            ORDER BY 2 DESC
            """
        )
        print("\n=== false updates by path transition ===")
        for bucket, count in cur.fetchall():
            print(f"  {bucket}: {count}")

        cur.execute(
            """
            SELECT us.source_name, count(*)
            FROM document_versions dv
            JOIN url_sources us ON us.id = dv.url_source_id
            JOIN document_versions pv ON pv.document_id = dv.document_id AND pv.id = (
                SELECT max(dv2.id) FROM document_versions dv2
                WHERE dv2.document_id = dv.document_id AND dv2.id < dv.id
            )
            WHERE dv.change_type = '更新'
              AND dv.file_hash = pv.file_hash
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT 12
            """
        )
        print("\n=== false updates by url source ===")
        for name, count in cur.fetchall():
            print(f"  {name}: {count}")

        cur.execute(
            """
            SELECT dv.id, d.standard_no, dv.file_name,
                   left(pv.file_path, 60) AS prev_path,
                   left(dv.file_path, 60) AS new_path
            FROM document_versions dv
            JOIN documents d ON d.id = dv.document_id
            JOIN document_versions pv ON pv.document_id = dv.document_id AND pv.id = (
                SELECT max(dv2.id) FROM document_versions dv2
                WHERE dv2.document_id = dv.document_id AND dv2.id < dv.id
            )
            WHERE dv.change_type = '更新'
              AND dv.file_hash = pv.file_hash
            ORDER BY dv.id DESC
            LIMIT 8
            """
        )
        print("\n=== samples path-only changes ===")
        for row in cur.fetchall():
            print(f"  dv#{row[0]} {row[1]} {row[2]}")
            print(f"    prev: {row[3]}")
            print(f"    new : {row[4]}")


if __name__ == "__main__":
    main()
