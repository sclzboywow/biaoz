from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1]
BACKEND = ROOT if (ROOT / "app").is_dir() else ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import batch2_adapters  # noqa: F401,E402
from app import models  # noqa: E402
from app.batch2_adapters import BATCH2_ADAPTER_KEYS  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402
from app.batch2_file_ingest_service import discover_files_for_source  # noqa: E402
from app.trusted_source_adapters import TrustedSourceSyncOptions, registry  # noqa: E402


def _source_snapshot(adapter_keys: set[str], source_ids: list[int] | None, *, enabled_only: bool) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        ensure_default_trusted_sources(db)
        query = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key.in_(adapter_keys))
        if enabled_only:
            query = query.filter(models.TrustedSource.enabled.is_(True))
        if source_ids:
            query = query.filter(models.TrustedSource.id.in_(source_ids))
        sources = []
        for source in query.order_by(models.TrustedSource.id):
            if registry.get(source.adapter_key or "") is None:
                continue
            sources.append(
                {
                    "id": source.id,
                    "source_name": source.source_name,
                    "adapter_key": source.adapter_key,
                    "enabled": source.enabled,
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
            if ok and not args.no_detail and not args.skip_file_discovery:
                from app.batch2_admission import batch2_pipeline_enabled

                if batch2_pipeline_enabled(db):
                    discovery = discover_files_for_source(db, source_id=source["id"], limit=max(50, args.pages * 20))
                    payload["file_discovery"] = discovery
                else:
                    payload["file_discovery"] = {"skipped": True, "reason": "batch2_pipeline_disabled"}
            return payload
        except Exception as exc:
            return {**source, "ok": False, "error": repr(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync batch-2 trusted sources (isolated from default parallel sync)")
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--no-detail", action="store_true")
    parser.add_argument("--skip-file-discovery", action="store_true", help="Skip post-sync official file discovery")
    parser.add_argument("--only-pending-categories", action="store_true")
    parser.add_argument("--include-disabled", action="store_true", help="Also sync sources with enabled=false")
    parser.add_argument("--adapter-key", action="append", default=[])
    parser.add_argument("--source-id", type=int, action="append", default=[])
    args = parser.parse_args()

    adapter_keys = set(args.adapter_key or BATCH2_ADAPTER_KEYS)
    sources = _source_snapshot(adapter_keys, args.source_id or None, enabled_only=not args.include_disabled)
    if not sources:
        print("batch2_sync_plan", json.dumps({"sources": 0, "adapter_keys": sorted(adapter_keys)}, ensure_ascii=False))
        return 0

    print(
        "batch2_sync_plan",
        json.dumps(
            {
                "sources": len(sources),
                "workers": args.workers,
                "pages": args.pages,
                "adapter_keys": sorted(adapter_keys),
            },
            ensure_ascii=False,
        ),
    )

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(_sync_one, source, args) for source in sources]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print("batch2_sync_result", json.dumps(result, ensure_ascii=False, default=str))

    ok_count = sum(1 for item in results if item.get("ok"))
    print(
        "batch2_sync_summary",
        json.dumps({"ok": ok_count, "failed": len(results) - ok_count, "total": len(results)}, ensure_ascii=False),
    )
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
