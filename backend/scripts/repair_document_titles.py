"""Repair Document.title from UrlSource.source_name for noisy SPC/URL archives."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from sqlalchemy import select

from app import models
from app.database import SessionLocal
from app.document_classification_service import (
    _preferred_source_display_name,
    sanitize_document_title,
)


def repair_titles(*, dry_run: bool = True, limit: int | None = None) -> dict[str, int]:
    db = SessionLocal()
    scanned = 0
    updated = 0
    try:
        statement = (
            select(models.Document, models.UrlSource)
            .join(models.DocumentVersion, models.DocumentVersion.document_id == models.Document.id)
            .join(models.UrlSource, models.UrlSource.id == models.DocumentVersion.url_source_id)
            .where(models.DocumentVersion.is_current.is_(True))
            .order_by(models.Document.id.desc())
        )
        if limit:
            statement = statement.limit(limit)
        rows = db.execute(statement).all()
        seen: set[int] = set()
        for document, source in rows:
            if document.id in seen:
                continue
            seen.add(document.id)
            scanned += 1
            preferred = _preferred_source_display_name(source, None)
            if not preferred:
                continue
            new_title = sanitize_document_title(preferred, standard_no=document.standard_no)
            if not new_title or new_title == document.title:
                continue
            if len(document.title or "") <= len(new_title):
                continue
            if dry_run:
                print(f"[dry-run] doc={document.id} {document.title[:60]!r} -> {new_title!r}")
            else:
                document.title = new_title[:500]
            updated += 1
        if not dry_run:
            db.commit()
    finally:
        db.close()
    return {"scanned": scanned, "updated": updated}


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair long Document.title values from UrlSource.source_name")
    parser.add_argument("--apply", action="store_true", help="Persist changes (default: dry run)")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    stats = repair_titles(dry_run=not args.apply, limit=args.limit)
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
