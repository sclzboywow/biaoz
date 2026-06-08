from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app import spc_online_adapter  # noqa: F401,E402
from app.database import SessionLocal  # noqa: E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402
from app.trusted_source_adapters import TrustedSourceSyncOptions, registry  # noqa: E402


def find_spc_source_id() -> int:
    with SessionLocal() as db:
        ensure_default_trusted_sources(db)
        source = (
            db.query(models.TrustedSource)
            .filter(models.TrustedSource.adapter_key == spc_online_adapter.SpcOnlineAdapter.adapter_key)
            .first()
        )
        if source is None:
            raise SystemExit("SPC trusted source not found")
        return source.id


def main() -> int:
    parser = argparse.ArgumentParser(description="Slow-sync SPC standard online metadata as a separate trusted source.")
    parser.add_argument("--source-id", type=int, default=None)
    parser.add_argument("--pages", type=int, default=1, help="Pages per category in this run.")
    parser.add_argument(
        "--category",
        choices=[item.type_code for item in spc_online_adapter.SPC_CATEGORIES]
        + [item.category_id for item in spc_online_adapter.SPC_CATEGORIES],
        help="Limit to one SPC category, e.g. CN, QT, TC, DFBZ, QYBZ, JJ.",
    )
    parser.add_argument("--sctype", help="Limit to one SPC subcategory code, e.g. A, YY, DB11.")
    parser.add_argument("--scname", help="SPC subcategory display name.")
    parser.add_argument("--category-limit", type=int, default=None)
    parser.add_argument("--only-pending-categories", action="store_true")
    parser.add_argument("--no-detail", action="store_true")
    args = parser.parse_args()

    source_id = args.source_id or find_spc_source_id()
    category_id = args.category
    if args.sctype:
        if not args.category:
            raise SystemExit("--sctype requires --category")
        category_id = f"{args.category}:{args.sctype}:{args.scname or ''}"
    with SessionLocal() as db:
        adapter = registry.get(spc_online_adapter.SpcOnlineAdapter.adapter_key)
        if adapter is None:
            raise SystemExit("SPC adapter is not registered")
        result = adapter.sync(
            db,
            source_id,
            TrustedSourceSyncOptions(
                max_pages=min(max(args.pages, 1), 500),
                include_detail=not args.no_detail,
                category_id=category_id,
                only_pending_categories=args.only_pending_categories,
                category_limit=args.category_limit,
            ),
        )
    print("spc_sync_result " + json.dumps(result.__dict__, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
