from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.samr_public_adapters import _detail_hash, _system_status, _upsert_resource  # noqa: E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402
from app.spc_online_adapter import SPC_BASE_URL, SpcOnlineAdapter  # noqa: E402
from scripts.sync_spc_advanced_slices_parallel import _advanced_payload, _parse_advanced_items, AdvancedSlice, STATUS_WORDS  # noqa: E402


PAGE_SIZE = 10
REMOTE_PAGE_LIMIT = 30
DEFAULT_MAX_TOTAL = PAGE_SIZE * REMOTE_PAGE_LIMIT
CCS_ROOTS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
DEFAULT_START_DATE = "1978-01-01"
DEFAULT_END_DATE = "2030-12-31"


@dataclass(frozen=True)
class Condition:
    ccs: str = ""
    stdno: str = ""
    status: str = ""
    date_field: str = ""
    start_date: str = ""
    end_date: str = ""

    @property
    def key(self) -> str:
        ccs = self.ccs or "all"
        stdno = self.stdno or "all"
        status = self.status or "all"
        date_part = f"{self.date_field}_{self.start_date}_{self.end_date}" if self.date_field else "all_dates"
        raw = json.dumps(self.__dict__, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        safe = re.sub(r"[^0-9A-Za-z]+", "_", f"{date_part}_{ccs}_{stdno}").strip("_").lower()
        return f"spc_cn_full_{digest}_{safe or 'all'}"

    @property
    def label(self) -> str:
        parts = ["CN"]
        if self.status:
            parts.append(f"status:{self.status}")
        if self.date_field:
            parts.append(f"{self.date_field}:{self.start_date}..{self.end_date}")
        if self.ccs:
            parts.append(f"CCS:{self.ccs}")
        if self.stdno:
            parts.append(f"stdno:{self.stdno}")
        return " / ".join(parts)


def _now() -> datetime:
    return datetime.now(UTC)


def _source_id() -> int:
    with SessionLocal() as db:
        ensure_default_trusted_sources(db)
        source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == SpcOnlineAdapter.adapter_key).first()
        if source is None:
            raise SystemExit("SPC trusted source not found")
        return source.id


def _payload(condition: Condition, page_index: int) -> dict[str, str]:
    slice_item = AdvancedSlice("CN", condition.stdno, "stdno")
    payload = _advanced_payload(slice_item, page_index)
    if not condition.stdno:
        payload["stdno"] = ""
    payload["a825"] = condition.ccs
    payload["standStatus"] = condition.status
    if condition.date_field == "issue":
        payload["issueDateStart"] = condition.start_date
        payload["issueDateEnd"] = condition.end_date
    elif condition.date_field == "effective":
        payload["a205Start"] = condition.start_date
        payload["a205End"] = condition.end_date
    return payload


def _fetch(client: httpx.Client, condition: Condition, page_index: int, retries: int) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.post(
                f"{SPC_BASE_URL}/advancedsearch",
                data=_payload(condition, page_index),
                headers={"Referer": f"{SPC_BASE_URL}/advancedsearch"},
            )
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt >= retries:
                raise
            time.sleep(min(30.0, (2**attempt) + random.uniform(0.2, 1.2)))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("SPC request failed without exception")


def _count(client: httpx.Client, condition: Condition, retries: int) -> tuple[int, list[dict]]:
    response = _fetch(client, condition, 0, retries)
    items, total = _parse_advanced_items(response.text, "CN")
    return int(total if total is not None else len(items)), items


def _children(condition: Condition) -> list[Condition]:
    if not condition.status:
        return [Condition(status=item) for item in STATUS_WORDS]
    if not condition.date_field and not condition.ccs and not condition.stdno:
        return [
            Condition(status=condition.status, date_field="issue", start_date=DEFAULT_START_DATE, end_date=DEFAULT_END_DATE),
            Condition(status=condition.status, date_field="effective", start_date=DEFAULT_START_DATE, end_date=DEFAULT_END_DATE),
        ]

    if condition.date_field and condition.start_date and condition.end_date:
        start = date.fromisoformat(condition.start_date)
        end = date.fromisoformat(condition.end_date)
        if start < end:
            middle = start + ((end - start) // 2)
            return [
                Condition(condition.ccs, condition.stdno, condition.status, condition.date_field, start.isoformat(), middle.isoformat()),
                Condition(condition.ccs, condition.stdno, condition.status, condition.date_field, (middle + timedelta(days=1)).isoformat(), end.isoformat()),
            ]

    if not condition.ccs:
        return [
            Condition(item, condition.stdno, condition.status, condition.date_field, condition.start_date, condition.end_date)
            for item in CCS_ROOTS
        ]
    if not condition.stdno:
        return (
            [Condition(condition.ccs, f"GB/T {digit}", condition.status, condition.date_field, condition.start_date, condition.end_date) for digit in "0123456789"]
            + [Condition(condition.ccs, f"GB {digit}", condition.status, condition.date_field, condition.start_date, condition.end_date) for digit in "0123456789"]
            + [Condition(condition.ccs, "GB/Z", condition.status, condition.date_field, condition.start_date, condition.end_date)]
            + [Condition(condition.ccs, "GBJ", condition.status, condition.date_field, condition.start_date, condition.end_date)]
        )

    for prefix in ("GB/T ", "GB/Z ", "GB ", "GBJ "):
        if condition.stdno.startswith(prefix):
            tail = condition.stdno[len(prefix) :]
            if tail and tail[-1].isdigit() and len(tail) < 8:
                return [
                    Condition(condition.ccs, f"{condition.stdno}{digit}", condition.status, condition.date_field, condition.start_date, condition.end_date)
                    for digit in "0123456789"
                ]

    if condition.stdno == "GB/Z":
        return [Condition(condition.ccs, f"GB/Z {digit}", condition.status, condition.date_field, condition.start_date, condition.end_date) for digit in "0123456789"]
    if condition.stdno == "GBJ":
        return [Condition(condition.ccs, f"GBJ {digit}", condition.status, condition.date_field, condition.start_date, condition.end_date) for digit in "0123456789"]
    return []


def _ensure_category(db, source: models.TrustedSource, condition: Condition, total: int) -> models.SourceCategory:
    category = (
        db.query(models.SourceCategory)
        .filter(models.SourceCategory.source_id == source.id, models.SourceCategory.source_category_id == condition.key)
        .first()
    )
    source_url = f"{SPC_BASE_URL}/advancedsearch?a825={condition.ccs}&stdno={condition.stdno}"
    category_path = f"中国标准在线服务网 / 国家标准全量切片 / {condition.label}"
    if category is None:
        category = models.SourceCategory(
            source_id=source.id,
            source_category_id=condition.key,
            category_name=f"国家标准全量切片 {condition.label}",
            category_path=category_path,
            source_url=source_url,
            resource_count=total,
            sync_status="待同步",
        )
        db.add(category)
        db.flush()
    else:
        category.category_name = f"国家标准全量切片 {condition.label}"
        category.category_path = category_path
        category.source_url = source_url
        category.resource_count = total
    return category


def _sync_terminal_slice(
    client: httpx.Client,
    *,
    source_id: int,
    condition: Condition,
    total: int,
    delay: float,
    retries: int,
) -> dict:
    pages = min(REMOTE_PAGE_LIMIT, max(1, math.ceil(total / PAGE_SIZE)))
    created = skipped = updated = errors = 0

    with SessionLocal() as db:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise RuntimeError(f"SPC trusted source missing: {source_id}")
        category = _ensure_category(db, source, condition, total)
        if category.sync_status == "已同步" and (category.last_synced_page or 0) >= pages:
            return {
                "condition": condition.__dict__,
                "total": total,
                "pages": 0,
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "errors": 0,
                "status": "already_synced",
            }
        start_page = max(0, category.last_synced_page or 0)
        category.sync_status = "同步中"
        category.last_sync_started_at = _now()
        category.last_sync_error = None
        db.commit()

    for page_index in range(start_page, pages):
        try:
            response = _fetch(client, condition, page_index, retries)
            items, _page_total = _parse_advanced_items(response.text, "CN")
        except Exception as exc:
            errors += 1
            with SessionLocal() as db:
                category = (
                    db.query(models.SourceCategory)
                    .filter(models.SourceCategory.source_id == source_id, models.SourceCategory.source_category_id == condition.key)
                    .first()
                )
                if category is not None:
                    category.last_sync_error = repr(exc)
                    category.sync_status = "待同步"
                    db.commit()
            break

        if not items:
            break

        with SessionLocal() as db:
            source = db.get(models.TrustedSource, source_id)
            category = (
                db.query(models.SourceCategory)
                .filter(models.SourceCategory.source_id == source_id, models.SourceCategory.source_category_id == condition.key)
                .first()
            )
            for item in items:
                exists = (
                    db.query(models.StandardResource.id)
                    .filter(models.StandardResource.source_id == source_id, models.StandardResource.source_book_id == item["source_item_id"])
                    .first()
                )
                if exists is not None:
                    skipped += 1
                    continue

                summary = f"SPC国家标准全量切片：{condition.label}\n详情页：{item.get('detail_url') or ''}"
                detail_hash = _detail_hash(item)
                resource, was_created = _upsert_resource(
                    db,
                    source,
                    item["source_item_id"],
                    {
                        "standard_no": item["standard_no"],
                        "source_status_raw": item.get("source_status"),
                        "standard_name": item.get("standard_name") or item["standard_no"],
                        "resource_type": "国家标准",
                        "source_status": item.get("source_status"),
                        "system_status": _system_status(item.get("source_status")),
                        "publish_date": item.get("publish_date"),
                        "effective_date": item.get("effective_date"),
                        "summary": summary,
                        "keywords": condition.ccs or None,
                        "source_category_path": category.category_path if category else None,
                        "detail_url": item.get("detail_url"),
                        "pdf_trial_url": f"{SPC_BASE_URL}/stdlib/stdonline",
                        "detail_hash": detail_hash,
                    },
                    evidence_summary=summary,
                )
                created += 1 if was_created else 0
                updated += 0 if was_created else 1
                db.add(
                    models.StandardEvidence(
                        standard_resource_id=resource.id,
                        source_name=source.source_name,
                        source_level=source.trust_level,
                        source_url=item.get("detail_url"),
                        raw_status_text=item.get("source_status"),
                        parsed_status=resource.system_status,
                        page_summary=summary,
                        page_html_hash=detail_hash,
                        evidence_note="SPC国家标准全量切片列表快照入库。",
                    )
                )
            if category is not None:
                category.last_synced_page = page_index + 1
            db.commit()
        if delay > 0:
            time.sleep(delay)

    with SessionLocal() as db:
        category = (
            db.query(models.SourceCategory)
            .filter(models.SourceCategory.source_id == source_id, models.SourceCategory.source_category_id == condition.key)
            .first()
        )
        if category is not None:
            category.last_sync_finished_at = _now()
            category.last_synced_at = category.last_sync_finished_at
            category.sync_status = "同步失败" if errors else ("已同步" if (category.last_synced_page or 0) >= pages else "待同步")
            db.commit()

    return {
        "condition": condition.__dict__,
        "total": total,
        "pages": pages - start_page if not errors else None,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


def run(args: argparse.Namespace) -> int:
    source_id = args.source_id or _source_id()
    queue: deque[Condition] = deque([Condition(status=item) for item in args.status] if args.status else [Condition()])
    visited: set[str] = set()
    terminal_processed = 0
    summary = {"counted": 0, "split": 0, "terminal": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0, "blocked": 0}

    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        while queue:
            if args.max_counted_slices is not None and summary["counted"] >= args.max_counted_slices:
                break
            condition = queue.popleft()
            if condition.key in visited:
                continue
            visited.add(condition.key)

            try:
                total, _items = _count(client, condition, args.retries)
            except Exception as exc:
                summary["errors"] += 1
                print("spc_cn_full_count_error " + json.dumps({"condition": condition.__dict__, "error": repr(exc)}, ensure_ascii=False), flush=True)
                continue

            summary["counted"] += 1
            children = _children(condition) if total > args.max_total else []
            print(
                "spc_cn_full_slice "
                + json.dumps(
                    {
                        "condition": condition.__dict__,
                        "total": total,
                        "children": len(children),
                        "terminal": total <= args.max_total,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

            if children:
                summary["split"] += 1
                queue.extend(children)
                continue
            if total > args.max_total:
                summary["blocked"] += 1
                print(
                    "spc_cn_full_blocked "
                    + json.dumps({"condition": condition.__dict__, "total": total, "reason": "no finer split rule"}, ensure_ascii=False),
                    flush=True,
                )
                continue

            summary["terminal"] += 1
            if total == 0:
                continue
            if args.dry_run:
                continue
            if args.max_terminal_slices is not None and terminal_processed >= args.max_terminal_slices:
                break
            result = _sync_terminal_slice(
                client,
                source_id=source_id,
                condition=condition,
                total=total,
                delay=args.delay,
                retries=args.retries,
            )
            terminal_processed += 1
            summary["created"] += int(result.get("created") or 0)
            summary["updated"] += int(result.get("updated") or 0)
            summary["skipped"] += int(result.get("skipped") or 0)
            summary["errors"] += int(result.get("errors") or 0)
            print("spc_cn_full_result " + json.dumps(result, ensure_ascii=False, default=str), flush=True)

    print("spc_cn_full_summary " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["errors"] == 0 and summary["blocked"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Exhaustively sync SPC national-standard metadata by recursively splitting queries under the 30-page SPC limit.")
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--max-total", type=int, default=DEFAULT_MAX_TOTAL)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-counted-slices", type=int)
    parser.add_argument("--max-terminal-slices", type=int)
    parser.add_argument("--status", action="append", choices=STATUS_WORDS, help="Limit the run to one status. Can be repeated.")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
