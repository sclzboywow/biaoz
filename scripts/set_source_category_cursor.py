from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Set trusted source category cursor.")
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--category-id", required=True)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--status", default="待同步")
    args = parser.parse_args()

    with SessionLocal() as db:
        category = (
            db.query(models.SourceCategory)
            .filter(
                models.SourceCategory.source_id == args.source_id,
                models.SourceCategory.source_category_id == args.category_id,
            )
            .first()
        )
        if category is None:
            raise SystemExit("category not found")
        category.last_synced_page = args.page
        category.sync_status = args.status
        category.last_sync_error = None
        db.commit()
        print(f"updated source_id={args.source_id} category_id={args.category_id} page={args.page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
