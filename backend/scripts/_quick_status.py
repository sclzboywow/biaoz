import psycopg

with psycopg.connect("postgresql://biaoz:biaoz@localhost:5432/biaoz") as conn:
    cur = conn.cursor()
    for label, sql in [
        ("settings", "SELECT key, value FROM system_settings WHERE key IN ('batch2_file_ingest_enabled','batch2_pipeline_enabled','ingest_enabled') ORDER BY key"),
        ("change_type", "SELECT change_type, count(*) FROM document_versions GROUP BY 1 ORDER BY 2 DESC"),
        ("db_size", "SELECT pg_size_pretty(pg_database_size(current_database()))"),
        ("documents", "SELECT count(*) FROM documents"),
        ("dv_current_baidu", "SELECT count(*) FROM document_versions WHERE is_current AND (file_path LIKE 'baidupan:%' OR remark LIKE '%baidu_pan_sync=%')"),
    ]:
        cur.execute(sql)
        rows = cur.fetchall()
        print(label + ":", rows)
