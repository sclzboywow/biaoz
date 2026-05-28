from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.guobiao_discovery import sync_discovered_sublibs  # noqa: E402
from app.migrations import run_lightweight_migrations  # noqa: E402
from app.models import TrustedSource  # noqa: E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()
    with SessionLocal() as db:
        ensure_default_trusted_sources(db)
        source = db.query(TrustedSource).filter(TrustedSource.source_name == "国标电子书库").first()
        if source is None:
            raise RuntimeError("国标电子书库可信源不存在")
        stats = sync_discovered_sublibs(db, source)
    for key, value in stats.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
