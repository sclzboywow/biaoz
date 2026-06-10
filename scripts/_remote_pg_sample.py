import psycopg

conn = psycopg.connect("postgresql://biaoz:biaoz@localhost:5432/biaoz")
cur = conn.cursor()
cur.execute(
    """
    SELECT dv.file_path, left(dv.remark, 200)
    FROM document_versions dv
    WHERE dv.is_current IS TRUE
      AND (dv.file_path LIKE 'baidupan:%' OR dv.remark LIKE '%baidu_pan_sync=%')
    LIMIT 3
    """
)
for row in cur.fetchall():
    print("---")
    print(row[0][:120] if row[0] else None)
    print(row[1])
