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

# Any document_version in DB (all sources) - sample paths
print("all_sources_with_dv", db.execute(text("SELECT COUNT(*) FROM document_versions WHERE is_current=true")).scalar())

# Group standard pattern T/ in standard_no with file somewhere
rows = db.execute(
    text(
        """
        SELECT sr.id, sr.source_id, sr.standard_no, sr.detail_url, sr.sync_status, dv.file_path
        FROM standard_resources sr
        JOIN url_sources us ON us.url = sr.detail_url
        JOIN document_versions dv ON dv.url_source_id = us.id AND dv.is_current = true
        WHERE sr.standard_no LIKE 'T/%'
          AND btrim(dv.file_path) <> ''
        ORDER BY sr.id DESC
        LIMIT 15
        """
    )
).all()
print("T_slash_with_file_any_source", len(rows))
for r in rows[:8]:
    print(r)

# ttbz metadata 已同步 - try oldest entries (maybe early successes?)
old_synced = db.execute(
    text(
        """
        SELECT id, standard_no, detail_url, source_book_id, last_synced_at
        FROM standard_resources
        WHERE source_id = 6 AND sync_status = '已同步'
        ORDER BY id ASC
        LIMIT 8
        """
    )
).all()
print("oldest_synced_ttbz_metadata")
for r in old_synced:
    print(r)

db.close()
