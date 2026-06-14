import psycopg

with psycopg.connect("postgresql://biaoz:biaoz@localhost:5432/biaoz") as conn:
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM document_versions")
    total = cur.fetchone()[0]
    cur.execute(
        """
        SELECT count(*) FROM (
            SELECT document_id, lower(file_hash)
            FROM document_versions
            WHERE file_hash IS NOT NULL AND btrim(file_hash) <> ''
            GROUP BY 1, 2
            HAVING count(*) > 1
        ) x
        """
    )
    dup_groups = cur.fetchone()[0]
    cur.execute(
        """
        SELECT count(*)
        FROM document_versions dv
        WHERE EXISTS (
            SELECT 1 FROM document_versions earlier
            WHERE earlier.document_id = dv.document_id
              AND lower(earlier.file_hash) = lower(dv.file_hash)
              AND earlier.id < dv.id
        )
        """
    )
    dup_rows = cur.fetchone()[0]
    cur.execute(
        """
        SELECT pid, state, wait_event_type, left(query, 100)
        FROM pg_stat_activity
        WHERE datname = 'biaoz' AND state <> 'idle' AND pid <> pg_backend_pid()
        """
    )
    active = cur.fetchall()
print("document_versions_total", total)
print("duplicate_hash_groups", dup_groups)
print("duplicate_rows_to_remove", dup_rows)
print("active_queries", len(active))
for row in active:
    print(" ", row)
