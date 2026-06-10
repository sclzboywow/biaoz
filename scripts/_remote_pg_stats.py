import os
import psycopg

conn = psycopg.connect("postgresql://biaoz:biaoz@localhost:5432/biaoz")
cur = conn.cursor()
for q in [
    "SELECT count(*) FROM documents",
    "SELECT count(*) FROM standard_resources",
    "SELECT count(*) FROM document_versions WHERE is_current IS TRUE",
    "SELECT count(*) FROM document_versions WHERE is_current IS TRUE AND file_path LIKE 'baidupan:%'",
    "SELECT id, standard_no, title FROM documents WHERE standard_no IS NOT NULL ORDER BY id DESC LIMIT 3",
]:
    cur.execute(q)
    print(q.split("FROM")[-1].strip()[:40], "->", cur.fetchone() if "LIMIT" not in q else cur.fetchall())
