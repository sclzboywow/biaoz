from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal  # noqa: E402
from app.guobiao_sync import sync_guobiao_resources  # noqa: E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync guobiao trusted source resources.")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--sublib-id", type=int)
    parser.add_argument("--no-detail", action="store_true")
    parser.add_argument("--all-pages", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        ensure_default_trusted_sources(db)
        stats = sync_guobiao_resources(
            db,
            max_pages_per_sublib=99999 if args.all_pages else args.pages,
            include_detail=not args.no_detail,
            sublib_id=args.sublib_id,
        )
    for key, value in stats.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
