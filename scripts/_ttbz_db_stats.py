from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import text
from app.database import SessionLocal

db = SessionLocal()
sid = db.execute(text("SELECT id FROM trusted_sources WHERE adapter_key='samr_group_standard_public'")).scalar()
print("source_id", sid)

queries = {
    "total_resources": "SELECT COUNT(*) FROM standard_resources WHERE source_id=:sid",
    "sync_status_已同步": "SELECT COUNT(*) FROM standard_resources WHERE source_id=:sid AND sync_status='已同步'",
    "sync_status_文件采集失败": "SELECT COUNT(*) FROM standard_resources WHERE source_id=:sid AND sync_status='文件采集失败'",
    "sync_status_文件不可下载": "SELECT COUNT(*) FROM standard_resources WHERE source_id=:sid AND sync_status='文件不可下载'",
    "detail_url_ttbz": "SELECT COUNT(*) FROM standard_resources WHERE source_id=:sid AND detail_url LIKE 'https://www.ttbz.org.cn/%'",
    "with_url_source": """
        SELECT COUNT(DISTINCT sr.id) FROM standard_resources sr
        JOIN url_sources us ON us.url = sr.detail_url WHERE sr.source_id=:sid
    """,
    "with_document_version": """
        SELECT COUNT(DISTINCT sr.id) FROM standard_resources sr
        JOIN url_sources us ON us.url = sr.detail_url
        JOIN document_versions dv ON dv.url_source_id=us.id AND dv.is_current=true
        WHERE sr.source_id=:sid
    """,
    "with_local_file_path": """
        SELECT COUNT(DISTINCT sr.id) FROM standard_resources sr
        JOIN url_sources us ON us.url = sr.detail_url
        JOIN document_versions dv ON dv.url_source_id=us.id AND dv.is_current=true
        WHERE sr.source_id=:sid AND dv.file_path NOT LIKE 'baidupan:%' AND btrim(dv.file_path) <> ''
    """,
    "any_channel_ttbz_url": """
        SELECT COUNT(*) FROM document_versions dv
        JOIN url_sources us ON us.id=dv.url_source_id
        WHERE dv.is_current=true AND us.url LIKE 'https://www.ttbz.org.cn/standardDetail/%'
    """,
}
for name, sql in queries.items():
    print(name, db.execute(text(sql), {"sid": sid}).scalar())

# sample any ttbz document_versions
rows = db.execute(
    text(
        """
        SELECT sr.id, sr.standard_no, sr.sync_status, dv.file_path
        FROM document_versions dv
        JOIN url_sources us ON us.id = dv.url_source_id
        LEFT JOIN standard_resources sr ON sr.detail_url = us.url AND sr.source_id = :sid
        WHERE dv.is_current = true AND us.url LIKE 'https://www.ttbz.org.cn/standardDetail/%'
        ORDER BY dv.id DESC LIMIT 8
        """
    ),
    {"sid": sid},
).all()
print("samples_with_dv", len(rows))
for r in rows:
    print(r)

samples = db.execute(
    text(
        """
        SELECT id, standard_no, sync_status, detail_url, source_book_id
        FROM standard_resources
        WHERE source_id = :sid AND sync_status = '已同步'
        ORDER BY id DESC
        LIMIT 5
        """
    ),
    {"sid": sid},
).all()
print("synced_samples")
for s in samples:
    print(s)

# overlap: same standard_no exists in other source with document_version file
overlap = db.execute(
    text(
        """
        SELECT t.id, t.standard_no, t.detail_url, o.source_id AS other_source, dv.file_path
        FROM standard_resources t
        JOIN standard_resources o ON o.standard_no = t.standard_no AND o.source_id <> t.source_id
        JOIN url_sources us ON us.url = o.detail_url
        JOIN document_versions dv ON dv.url_source_id = us.id AND dv.is_current = true
        WHERE t.source_id = :sid
          AND t.sync_status IN ('文件采集失败', '文件不可下载')
          AND dv.file_path IS NOT NULL AND btrim(dv.file_path) <> ''
        ORDER BY t.id DESC
        LIMIT 10
        """
    ),
    {"sid": sid},
).scalar() if False else None

overlap_rows = db.execute(
    text(
        """
        SELECT t.id, t.standard_no, t.detail_url, o.source_id AS other_source, dv.file_path
        FROM standard_resources t
        JOIN standard_resources o ON o.standard_no = t.standard_no AND o.source_id <> t.source_id
        JOIN url_sources us ON us.url = o.detail_url
        JOIN document_versions dv ON dv.url_source_id = us.id AND dv.is_current = true
        WHERE t.source_id = :sid
          AND dv.file_path IS NOT NULL AND btrim(dv.file_path) <> ''
        ORDER BY t.id DESC
        LIMIT 10
        """
    ),
    {"sid": sid},
).all()
print("overlap_with_other_source_files", len(overlap_rows))
for r in overlap_rows[:5]:
    print(r)

db.close()
