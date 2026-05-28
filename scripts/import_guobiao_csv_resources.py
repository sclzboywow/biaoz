from __future__ import annotations

import argparse
import csv
import html
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402
from app.standard_number import normalize_standard_no  # noqa: E402
from app.status_calibration import attach_change_logs_to_documents, calibrate_resource_status  # noqa: E402


def clean(value: str | None) -> str:
    return html.unescape((value or "").strip())


def get_guobiao_source(db):
    ensure_default_trusted_sources(db)
    source = db.query(models.TrustedSource).filter(models.TrustedSource.source_name == "国标电子书库").first()
    if source is None:
        raise RuntimeError("国标电子书库可信源不存在")
    return source


def upsert_resource(db, source, row, keys) -> tuple[bool, models.StandardResource | None]:
    status_key, code_key, name_key, url_key = keys[:4]
    id_key = keys[4] if len(keys) > 4 else None

    standard_no = clean(row.get(status_key if False else code_key))
    standard_name = clean(row.get(name_key))
    source_status = clean(row.get(status_key))
    download_url = clean(row.get(url_key))
    source_book_id = clean(row.get(id_key)) if id_key else ""

    if not download_url or not standard_name:
        return False, None

    query = db.query(models.StandardResource).filter(models.StandardResource.source_id == source.id)
    if source_book_id:
        resource = query.filter(models.StandardResource.source_book_id == source_book_id).first()
    else:
        resource = query.filter(
            models.StandardResource.standard_no == standard_no,
            models.StandardResource.standard_name == standard_name,
        ).first()

    created = resource is None
    if resource is None:
        resource = models.StandardResource(
            source_id=source.id,
            source_book_id=source_book_id or None,
            source_name=source.source_name,
            standard_name=standard_name,
        )
        db.add(resource)
        db.flush()

    detail_url = (
        f"https://ebook.chinabuilding.com.cn/zbooklib/book/detail/show?SiteID=1&bookID={source_book_id}"
        if source_book_id
        else None
    )
    resource.standard_no = standard_no or None
    number_parts = normalize_standard_no(standard_no)
    resource.raw_standard_no = number_parts.raw
    resource.normalized_standard_no = number_parts.normalized
    resource.standard_prefix = number_parts.prefix
    resource.standard_main_no = number_parts.main_no
    resource.standard_year = number_parts.year
    resource.standard_revision_note = number_parts.revision_note
    resource.source_status_raw = source_status or None
    resource.standard_name = standard_name
    resource.resource_type = "国标电子书库资源"
    resource.source_status = source_status or None
    resource.system_status = "来源确认废止" if source_status == "废止" else "来源确认现行"
    resource.source_category_path = "国标电子书库 / CSV资源索引"
    resource.detail_url = detail_url
    resource.pdf_trial_url = download_url
    resource.source_confidence = source.trust_score
    resource.last_synced_at = datetime.now(UTC)
    resource.sync_status = "CSV基线同步"
    return created, resource


def import_csv(path: Path, encoding: str = "gb18030", batch_size: int = 1000) -> dict[str, int]:
    stats = {
        "rows": 0,
        "with_url": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "matches": 0,
        "sync_logs": 0,
        "alerts": 0,
        "linked_change_logs": 0,
    }
    seen_urls: set[str] = set()

    with SessionLocal() as db:
        source = get_guobiao_source(db)
        with path.open("r", encoding=encoding, newline="") as file_obj:
            reader = csv.DictReader(file_obj)
            if not reader.fieldnames or len(reader.fieldnames) < 4:
                raise ValueError("CSV 表头不完整")
            keys = reader.fieldnames[:5]

            for row in reader:
                stats["rows"] += 1
                url = clean(row.get(keys[3]))
                if not url:
                    stats["skipped"] += 1
                    continue
                if url in seen_urls:
                    stats["skipped"] += 1
                    continue
                seen_urls.add(url)
                stats["with_url"] += 1

                created, resource = upsert_resource(db, source, row, keys)
                if resource is None:
                    stats["skipped"] += 1
                    continue
                stats["created" if created else "updated"] += 1

                calibration = calibrate_resource_status(db, resource)
                stats["matches"] += calibration["matches"]
                stats["sync_logs"] += calibration["sync_logs"]
                stats["alerts"] += calibration["alerts"]
                stats["linked_change_logs"] += attach_change_logs_to_documents(db, resource)

                if stats["with_url"] % batch_size == 0:
                    db.commit()
        db.commit()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Guobiao CSV into trusted standard_resources.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--encoding", default="gb18030")
    args = parser.parse_args()
    csv_path = args.csv_path if args.csv_path.is_absolute() else ROOT / args.csv_path
    stats = import_csv(csv_path, args.encoding)
    for key, value in stats.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
