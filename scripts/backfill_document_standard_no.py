from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal  # noqa: E402
from app.models import Document, DocumentVersion, UrlSource  # noqa: E402


def extract_standard_no(remark: str | None) -> str | None:
    if not remark:
        return None
    match = re.search(r"编号：([^；;]+)", remark)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def main() -> None:
    updated = 0
    with SessionLocal() as db:
        rows = (
            db.query(Document, UrlSource)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .join(UrlSource, UrlSource.id == DocumentVersion.url_source_id)
            .filter((Document.standard_no.is_(None)) | (Document.standard_no == ""))
            .all()
        )
        for document, source in rows:
            standard_no = extract_standard_no(source.remark)
            if standard_no:
                document.standard_no = standard_no
                updated += 1
        db.commit()
    print(f"updated={updated}")


if __name__ == "__main__":
    main()
