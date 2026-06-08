from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import func  # noqa: E402

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect trusted source sync progress.")
    parser.add_argument("--source-id", type=int, action="append", dest="source_ids")
    args = parser.parse_args()

    with SessionLocal() as db:
        ensure_default_trusted_sources(db)
        query = db.query(models.TrustedSource)
        if args.source_ids:
            query = query.filter(models.TrustedSource.id.in_(args.source_ids))
        sources = query.order_by(models.TrustedSource.id).all()
        for source in sources:
            count = (
                db.query(func.count(models.StandardResource.id))
                .filter(models.StandardResource.source_id == source.id)
                .scalar()
            )
            categories = (
                db.query(models.SourceCategory)
                .filter(models.SourceCategory.source_id == source.id)
                .order_by(models.SourceCategory.id)
                .all()
            )
            print(
                "\t".join(
                    [
                        str(source.id),
                        source.source_name,
                        source.adapter_key or "",
                        str(count or 0),
                    ]
                )
            )
            for category in categories:
                print(
                    "\t".join(
                        [
                            "  category",
                            category.category_name,
                            category.sync_status or "",
                            str(category.last_synced_page or ""),
                            str(category.resource_count or ""),
                            category.last_sync_error or "",
                        ]
                    )
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
