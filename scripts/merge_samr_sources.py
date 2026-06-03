from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import SessionLocal  # noqa: E402
from app.models import SourceCategory, StandardResource, TrustedSource  # noqa: E402


OLD_ADAPTER = "samr_std_public"
NEW_ADAPTER = "samr_gb_all_public"


def merge() -> dict[str, int]:
    stats = {"moved": 0, "duplicates_marked": 0, "old_disabled": 0}
    with SessionLocal() as db:
        old = db.query(TrustedSource).filter(TrustedSource.adapter_key == OLD_ADAPTER).first()
        new = db.query(TrustedSource).filter(TrustedSource.adapter_key == NEW_ADAPTER).first()
        if old is None or new is None:
            raise SystemExit(f"source missing: old={bool(old)} new={bool(new)}")

        existing_book_ids = set(
            value
            for (value,) in db.query(StandardResource.source_book_id)
            .filter(StandardResource.source_id == new.id, StandardResource.source_book_id.isnot(None))
            .all()
            if value
        )
        existing_numbers = set(
            value
            for (value,) in db.query(StandardResource.normalized_standard_no)
            .filter(StandardResource.source_id == new.id, StandardResource.normalized_standard_no.isnot(None))
            .all()
            if value
        )

        for resource in db.query(StandardResource).filter(StandardResource.source_id == old.id).yield_per(500):
            same_book = resource.source_book_id and resource.source_book_id in existing_book_ids
            same_number = resource.normalized_standard_no and resource.normalized_standard_no in existing_numbers
            if same_book or same_number:
                resource.source_book_id = f"duplicate-old-source:{old.id}:{resource.source_book_id or resource.id}"
                resource.sync_status = "重复保留"
                stats["duplicates_marked"] += 1
                continue
            resource.source_id = new.id
            resource.source_name = new.source_name
            if resource.source_book_id:
                existing_book_ids.add(resource.source_book_id)
            if resource.normalized_standard_no:
                existing_numbers.add(resource.normalized_standard_no)
            stats["moved"] += 1

        old.enabled = False
        old.remark = ((old.remark or "") + "\n已合并到国家标准信息公共服务平台（全量），停止作为独立同步源。").strip()
        stats["old_disabled"] = 1

        for category in db.query(SourceCategory).filter(SourceCategory.source_id == old.id):
            category.sync_status = "已合并"
            category.last_sync_finished_at = datetime.now(UTC)
            category.last_sync_error = "已合并到全量国家标准库"

        db.commit()
    return stats


if __name__ == "__main__":
    for key, value in merge().items():
        print(f"{key}={value}")
