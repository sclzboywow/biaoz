from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)


@dataclass(frozen=True)
class Slice:
    category: str
    sctype: str
    scname: str

    @property
    def category_id(self) -> str:
        return f"{self.category}:{self.sctype}:{self.scname}"


def _load_app():
    from app import models, spc_online_adapter
    from app.database import SessionLocal
    from app.settings_store import ensure_default_trusted_sources
    from app.trusted_source_adapters import TrustedSourceSyncOptions, registry

    return models, spc_online_adapter, SessionLocal, ensure_default_trusted_sources, TrustedSourceSyncOptions, registry


def _source_id() -> int:
    models, spc_online_adapter, SessionLocal, ensure_default_trusted_sources, _, _ = _load_app()
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


def discover_slices(categories: list[str]) -> list[Slice]:
    _, spc_online_adapter, _, _, _, _ = _load_app()
    adapter = spc_online_adapter.SpcOnlineAdapter()
    discovered: list[Slice] = []
    pattern = re.compile(r"datalistquery\('([^']*)','([^']*)','([^']*)'\)")
    category_by_code = {item.type_code: item for item in spc_online_adapter.SPC_CATEGORIES}
    category_configs = [category_by_code[code] for code in categories if code in category_by_code]
    with adapter._client() as client:
        for config in category_configs:
            response = adapter._fetch(client, config.source_url)
            matches = pattern.findall(response.text)
            seen: set[tuple[str, str]] = set()
            for sctype, scname, category in matches:
                if category != config.type_code or not sctype:
                    continue
                key = (sctype, scname)
                if key in seen:
                    continue
                seen.add(key)
                discovered.append(Slice(category=category, sctype=sctype, scname=scname))
            if not seen:
                discovered.append(Slice(category=config.type_code, sctype="", scname=""))
    return discovered


def sync_slice(slice_item: Slice, *, source_id: int, pages: int, include_detail: bool) -> dict:
    _, spc_online_adapter, SessionLocal, _, TrustedSourceSyncOptions, registry = _load_app()
    adapter = registry.get(spc_online_adapter.SpcOnlineAdapter.adapter_key)
    if adapter is None:
        raise RuntimeError("SPC adapter is not registered")
    category_id = slice_item.category if not slice_item.sctype else slice_item.category_id
    with SessionLocal() as db:
        result = adapter.sync(
            db,
            source_id,
            TrustedSourceSyncOptions(
                max_pages=min(max(pages, 1), 500),
                include_detail=include_detail,
                category_id=category_id,
                only_pending_categories=True,
            ),
        )
    payload = {
        "category": slice_item.category,
        "sctype": slice_item.sctype,
        "scname": slice_item.scname,
        "result": result.__dict__,
    }
    print("spc_slice_result " + json.dumps(payload, ensure_ascii=False, default=str), flush=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync SPC metadata by subcategory slices in parallel.")
    parser.add_argument("--categories", nargs="+", default=["QT", "DFBZ", "TC", "QYBZ", "CN", "JJ"])
    parser.add_argument("--pages", type=int, default=500)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--page-delay", type=float, default=0.25)
    parser.add_argument("--detail-delay", type=float, default=0.0)
    parser.add_argument("--include-detail", action="store_true")
    parser.add_argument("--only", nargs="*", help="Optional sctype allow-list, e.g. YY DB11 A.")
    args = parser.parse_args()

    os.environ["SPC_PAGE_DELAY_SECONDS"] = str(args.page_delay)
    os.environ["SPC_DETAIL_DELAY_SECONDS"] = str(args.detail_delay)
    if not args.include_detail:
        os.environ["SPC_FAST_METADATA_ONLY"] = "1"

    source_id = _source_id()
    slices = discover_slices([item.upper() for item in args.categories])
    if args.only:
        allow = set(args.only)
        slices = [item for item in slices if item.sctype in allow or item.category in allow]
    print(
        "spc_slice_plan "
        + json.dumps([item.__dict__ for item in slices], ensure_ascii=False, default=str),
        flush=True,
    )

    errors = 0
    max_workers = max(1, min(args.workers, len(slices) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(sync_slice, item, source_id=source_id, pages=args.pages, include_detail=args.include_detail)
            for item in slices
        ]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                errors += 1
                print("spc_slice_error " + json.dumps({"error": repr(exc)}, ensure_ascii=False), flush=True)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
