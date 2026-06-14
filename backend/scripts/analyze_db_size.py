#!/usr/bin/env python3
"""Print PostgreSQL table sizes and bot-relevant row counts."""
import psycopg

DSN = "postgresql://biaoz:biaoz@localhost:5432/biaoz"


def main() -> None:
    with psycopg.connect(DSN) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT relname AS table_name,
                   pg_size_pretty(pg_total_relation_size(relid)) AS total,
                   pg_total_relation_size(relid) AS bytes
            FROM pg_catalog.pg_statio_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT 25
            """
        )
        rows = cur.fetchall()
        print("TOP TABLES:")
        for name, pretty, _ in rows:
            print(f"  {pretty:>10}  {name}")

        cur.execute(
            "SELECT pg_size_pretty(pg_database_size(current_database())), "
            "pg_database_size(current_database())"
        )
        db_pretty, db_bytes = cur.fetchone()
        print(f"\nDB TOTAL: {db_pretty} ({db_bytes} bytes)")

        counts = [
            ("documents", "SELECT count(*) FROM documents"),
            ("document_versions", "SELECT count(*) FROM document_versions"),
            ("dv_current", "SELECT count(*) FROM document_versions WHERE is_current"),
            ("standard_resources", "SELECT count(*) FROM standard_resources"),
            (
                "sr_with_std_no",
                """
                SELECT count(*) FROM standard_resources
                WHERE standard_no IS NOT NULL AND BTRIM(standard_no) <> ''
                """,
            ),
            (
                "dv_baidu_current",
                """
                SELECT count(*) FROM document_versions
                WHERE is_current
                  AND (
                    file_path LIKE 'baidupan:%'
                    OR remark LIKE '%baidu_pan_sync=%'
                  )
                """,
            ),
            ("standard_evidence", "SELECT count(*) FROM standard_evidence"),
        ]
        for label, sql in counts:
            cur.execute(sql)
            print(f"{label}: {cur.fetchone()[0]}")

        cur.execute(
            """
            SELECT relname,
                   pg_size_pretty(pg_total_relation_size('standard_resources'::regclass)),
                   pg_size_pretty(pg_total_relation_size('documents'::regclass)),
                   pg_size_pretty(pg_total_relation_size('document_versions'::regclass))
            """
        )
        print("\nBot core tables:", cur.fetchone())

        cur.execute(
            """
            SELECT SUM(pg_total_relation_size(relid))
            FROM pg_catalog.pg_statio_user_tables
            WHERE relname IN ('standard_resources', 'documents', 'document_versions', 'alembic_version')
            """
        )
        bot_bytes = cur.fetchone()[0] or 0
        print(f"Bot tables total: {bot_bytes / 1024 / 1024:.1f} MB")

        cur.execute(
            """
            SELECT SUM(pg_total_relation_size(relid))
            FROM pg_catalog.pg_statio_user_tables
            WHERE relname NOT IN ('standard_resources', 'documents', 'document_versions', 'alembic_version')
            """
        )
        other_bytes = cur.fetchone()[0] or 0
        print(f"Everything else: {other_bytes / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
