from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.standard_number import normalize_standard_no  # noqa: E402


def apply_parts(target, value: str | None) -> bool:
    parts = normalize_standard_no(value)
    changed = (
        target.raw_standard_no != parts.raw
        or target.normalized_standard_no != parts.normalized
        or target.standard_prefix != parts.prefix
        or target.standard_main_no != parts.main_no
        or target.standard_year != parts.year
        or target.standard_revision_note != parts.revision_note
    )
    if changed:
        target.raw_standard_no = parts.raw
        target.normalized_standard_no = parts.normalized
        target.standard_prefix = parts.prefix
        target.standard_main_no = parts.main_no
        target.standard_year = parts.year
        target.standard_revision_note = parts.revision_note
    return changed


def main() -> None:
    with SessionLocal() as db:
        documents = 0
        resources = 0
        for document in db.query(models.Document).yield_per(1000):
            if apply_parts(document, document.standard_no):
                documents += 1
        for resource in db.query(models.StandardResource).yield_per(1000):
            if apply_parts(resource, resource.standard_no):
                resource.source_status_raw = resource.source_status
                resources += 1
        db.commit()
    print(f"documents={documents}")
    print(f"standard_resources={resources}")


if __name__ == "__main__":
    main()
