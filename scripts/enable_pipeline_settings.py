"""Ensure pipeline-related settings are enabled."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal
from app.models import SystemSetting
from app.settings_store import ensure_default_settings, get_bool_setting

UPDATES = {
    "ingest_enabled": "true",
    "storage_backend": "dual",
    "storage_root": "G:/data/standard-docs",
    "storage_auto_create": "true",
    "storage_pause_download_if_unavailable": "true",
    "ocr_download_enabled": "true",
    "governance_mode_enabled": "true",
}


def main() -> int:
    with SessionLocal() as db:
        ensure_default_settings(db)
        for key, value in UPDATES.items():
            item = db.get(SystemSetting, key)
            if item is None:
                continue
            item.value = value
        db.commit()
        print("ingest_enabled", get_bool_setting(db, "ingest_enabled"))
        print("ocr_download_enabled", get_bool_setting(db, "ocr_download_enabled"))
        print("storage_backend", item.value if (item := db.get(SystemSetting, "storage_backend")) else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
