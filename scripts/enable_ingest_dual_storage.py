"""Enable file ingest and dual storage settings."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal
from app.models import SystemSetting
from app.settings_store import ensure_default_settings, get_bool_setting, get_setting

UPDATES = {
    "ingest_enabled": "true",
    "storage_backend": "dual",
    "storage_root": "G:/data/standard-docs",
    "storage_auto_create": "true",
    "storage_pause_download_if_unavailable": "true",
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
        print("storage_backend", get_setting(db, "storage_backend"))
        print("storage_root", get_setting(db, "storage_root"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
