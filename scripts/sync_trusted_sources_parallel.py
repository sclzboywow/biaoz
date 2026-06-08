from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app import samr_public_adapters  # noqa: F401,E402
from app import spc_online_adapter  # noqa: F401,E402
from app.database import SessionLocal  # noqa: E402
from app.guobiao_sync import sync_guobiao_resources  # noqa: F401,E402
from app.samr_std_sync import sync_samr_std_resources  # noqa: F401,E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402
from app.trusted_source_adapters import TrustedSourceSyncOptions, registry  # noqa: E402


DEFAULT_ADAPTER_KEYS = {
    "samr_industry_standard_public",
    "samr_local_standard_public",
    "samr_group_standard_public",
    "samr_enterprise_standard_public",
}


def _source_snapshot(include_gb: bool, source_ids: list[int] | None) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        ensure_default_trusted_sources(db)
        query = db.query(models.TrustedSource).filter(models.TrustedSource.enabled.is_(True))
        if source_ids:
            query = query.filter(models.TrustedSource.id.in_(source_ids))
        sources = []
        for source in query.order_by(models.TrustedSource.id):
            if not source.adapter_key:
                continue
            if not include_gb and source.adapter_key not in DEFAULT_ADAPTER_KEYS:
                continue
            if registry.get(source.adapter_key) is None:
                continue
            sources.append(
                {
                    "id": source.id,
                    "source_name": source.source_name,
                    "adapter_key": source.adapter_key,
                }
            )
        return sources


def _sync_one(source: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    with SessionLocal() as db:
        adapter = registry.get(source["adapter_key"])
        if adapter is None:
            return {**source, "ok": False, "error": f"adapter not found: {source['adapter_key']}"}
        try:
            result = adapter.sync(
                db,
                source["id"],
                TrustedSourceSyncOptions(
                    max_pages=args.pages,
                    include_detail=not args.no_detail,
                    only_pending_categories=args.only_pending_categories,
                ),
            )
            ok = result.errors == 0
            payload = {**source, "ok": ok, "stats": result.__dict__}
            if not ok:
                payload["error"] = f"sync completed with {result.errors} adapter error(s)"
            return payload
        except Exception as exc:
            return {**source, "ok": False, "error": repr(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync independent trusted sources concurrently.")
    parser.add_argument("--pages", type=int, default=1, help="Pages to sync per source in this run.")
    parser.add_argument("--workers", type=int, default=3, help="Maximum concurrent source workers.")
    parser.add_argument("--source-id", type=int, action="append", dest="source_ids", help="Limit to one source id; repeatable.")
    parser.add_argument("--include-gb", action="store_true", help="Also include registry-based GB sync sources.")
    parser.add_argument("--only-pending-categories", action="store_true")
    parser.add_argument("--no-detail", action="store_true")
    args = parser.parse_args()
    args.pages = min(max(args.pages, 1), 2000)
    args.workers = min(max(args.workers, 1), 8)

    sources = _source_snapshot(args.include_gb, args.source_ids)
    if not sources:
        print("no_sources=1")
        return 0

    print("sources=" + json.dumps(sources, ensure_ascii=False))
    with ThreadPoolExecutor(max_workers=min(args.workers, len(sources))) as executor:
        futures = [executor.submit(_sync_one, source, args) for source in sources]
        for future in as_completed(futures):
            print("sync_result " + json.dumps(future.result(), ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
