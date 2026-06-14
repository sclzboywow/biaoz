#!/usr/bin/env python3
"""Disable batch-2 formal file ingest in system_settings."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.database import SessionLocal
from app import models
from app.settings_store import ensure_default_settings, get_bool_setting


def main() -> int:
    with SessionLocal() as db:
        ensure_default_settings(db)
        setting = db.get(models.SystemSetting, "batch2_file_ingest_enabled")
        if setting is None:
            print(json.dumps({"error": "setting_not_found"}, ensure_ascii=False))
            return 1
        setting.value = "false"
        db.commit()
        print(
            json.dumps(
                {"batch2_file_ingest_enabled": get_bool_setting(db, "batch2_file_ingest_enabled", False)},
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
