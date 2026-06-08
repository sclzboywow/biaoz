from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.samr_public_adapters import _detail_hash, _parse_date, _system_status, _upsert_resource  # noqa: E402
from app.settings_store import ensure_default_trusted_sources  # noqa: E402
from app.spc_online_adapter import SPC_BASE_URL, SpcOnlineAdapter  # noqa: E402


CATEGORY_LABELS = {
    "CN": ("国家标准", "中国国家标准 GB"),
    "QT": ("行业标准", "中国行业标准 QT"),
    "DFBZ": ("地方标准", "地方标准 DFBZ"),
    "TC": ("团体标准", "团体标准 TC"),
    "QYBZ": ("企业标准", "企业标准 QYBZ"),
    "JJ": ("计量技术规范", "计量规程规范 JJ"),
}

STATUS_WORDS = ("即将实施", "现行", "废止转行标", "被代替", "废止")


@dataclass(frozen=True)
class AdvancedSlice:
    category: str
    token: str
    field: str = "stdno"

    @property
    def category_id(self) -> str:
        safe = re.sub(r"[^0-9A-Za-z]+", "_", self.token).strip("_").lower() or "all"
        return f"spc_adv_{self.category.lower()}_{self.field}_{safe}"

    @property
    def category_name(self) -> str:
        base = CATEGORY_LABELS.get(self.category, (self.category, self.category))[0]
        return f"{base} 高级检索 {self.field}:{self.token}"


def _now() -> datetime:
    return datetime.now(UTC)


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").replace("\u3000", " ").split())


def _parse_total_count(soup: BeautifulSoup) -> int | None:
    text = soup.get_text(" ", strip=True)
    for pattern in (r"共\s*([0-9,]+)\s*条记录", r"共\s*([0-9,]+)\s*条", r"([0-9,]+)\s*条记录"):
        match = re.search(pattern, text)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _advanced_payload(slice_item: AdvancedSlice, page_index: int) -> dict[str, str]:
    _, label = CATEGORY_LABELS.get(slice_item.category, (slice_item.category, slice_item.category))
    payload = {
        "standStatus": "",
        "pageIndex": str(page_index),
        "advancedStauts": "",
        "sc": slice_item.category,
        "sctype": "",
        "search_type1": label,
        "seniorOfsc": "",
        "search_type2": label,
        "level": "",
        "advancedlevel": "",
        "stdno": "",
        "stdname": "",
        "adoptno": "",
        "a404": "",
        "a825": "",
        "issueDateStart": "",
        "issueDateEnd": "",
        "a205Start": "",
        "a205End": "",
        "reader": "",
        "ownerDept": "",
        "issueDepart": "",
        "draftsDept": "",
    }
    payload[slice_item.field] = slice_item.token
    return payload


def _parse_advanced_items(html: str, category: str) -> tuple[list[dict], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for block in soup.select(".advanced-search-list"):
        detail_link = block.find("a", href=lambda href: href and "/online/" in href)
        detail_url = urljoin(SPC_BASE_URL, detail_link.get("href")) if detail_link else None
        if not detail_url:
            continue

        standard_no = None
        hidden_no = block.select_one(".span_stdno")
        if hidden_no:
            standard_no = _clean_text(hidden_no.get_text(" ", strip=True))
        if not standard_no:
            for span in block.find_all("span"):
                title = span.get("title") or span.get("alt")
                if title:
                    match = re.match(r"^\s*([A-Z0-9]+(?:\s*/\s*[A-Z0-9]+)?(?:\s+[0-9][^\s]*)?)", _clean_text(title))
                    if match:
                        standard_no = _clean_text(match.group(1).replace(" / ", "/"))
                        break
        if not standard_no:
            continue

        title_text = ""
        title_spans = [span for span in block.find_all("span") if span.get("title") or span.get("alt")]
        if len(title_spans) >= 2:
            title_text = _clean_text(title_spans[1].get("title") or title_spans[1].get_text(" ", strip=True))
        title_text = re.sub(rf"^{re.escape(standard_no)}\s*", "", title_text).strip() or standard_no

        text = block.get_text(" ", strip=True)
        source_status = next((word for word in STATUS_WORDS if word in text), None)
        publish_match = re.search(r"发布日期\s*[:：]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
        effective_match = re.search(r"实施日期\s*[:：]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
        source_item_id = detail_url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
        items.append(
            {
                "source_item_id": source_item_id,
                "standard_no": standard_no,
                "standard_name": title_text,
                "source_status": source_status,
                "publish_date": _parse_date(publish_match.group(1)) if publish_match else None,
                "effective_date": _parse_date(effective_match.group(1)) if effective_match else None,
                "detail_url": detail_url,
                "type_code": category,
            }
        )
    return items, _parse_total_count(soup)


def _source_id() -> int:
    with SessionLocal() as db:
        ensure_default_trusted_sources(db)
        source = db.query(models.TrustedSource).filter(models.TrustedSource.adapter_key == SpcOnlineAdapter.adapter_key).first()
        if source is None:
            raise SystemExit("SPC trusted source not found")
        return source.id


def _ensure_slice_category(db, source: models.TrustedSource, slice_item: AdvancedSlice, source_url: str) -> models.SourceCategory:
    category = (
        db.query(models.SourceCategory)
        .filter(models.SourceCategory.source_id == source.id, models.SourceCategory.source_category_id == slice_item.category_id)
        .first()
    )
    if category is None:
        category = models.SourceCategory(
            source_id=source.id,
            source_category_id=slice_item.category_id,
            category_name=slice_item.category_name,
            category_path=f"中国标准在线服务网 / 高级检索 / {slice_item.category} / {slice_item.field}:{slice_item.token}",
            source_url=source_url,
            sync_status="待同步",
        )
        db.add(category)
        db.flush()
    return category


def _fetch(client: httpx.Client, slice_item: AdvancedSlice, page_index: int, *, retries: int) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = client.post(
                f"{SPC_BASE_URL}/advancedsearch",
                data=_advanced_payload(slice_item, page_index),
                headers={"Referer": f"{SPC_BASE_URL}/advancedsearch"},
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code != 429 or attempt >= retries:
                raise
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt >= retries:
                raise
        time.sleep(min(30.0, (2**attempt) + random.uniform(0.2, 1.2)))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("advanced search request failed without exception")


def sync_slice(slice_item: AdvancedSlice, *, source_id: int, max_pages: int, delay: float, retries: int) -> dict:
    created = 0
    skipped = 0
    updated = 0
    pages = 0
    errors = 0
    seen_signatures: set[tuple[str, ...]] = set()
    first_total: int | None = None

    with SessionLocal() as db:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise RuntimeError(f"SPC trusted source missing: {source_id}")
        category_row = _ensure_slice_category(
            db,
            source,
            slice_item,
            f"{SPC_BASE_URL}/advancedsearch?{slice_item.field}={slice_item.token}",
        )
        if category_row.sync_status == "已同步":
            return {"slice": slice_item.__dict__, "pages": 0, "created": 0, "skipped": 0, "updated": 0, "status": "already_synced"}
        start_page = max(0, category_row.last_synced_page or 0)
        category_row.sync_status = "同步中"
        category_row.last_sync_started_at = _now()
        category_row.last_sync_error = None
        db.commit()

    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for page_index in range(start_page, start_page + max_pages):
            try:
                response = _fetch(client, slice_item, page_index, retries=retries)
                items, total_count = _parse_advanced_items(response.text, slice_item.category)
            except Exception as exc:
                errors += 1
                with SessionLocal() as db:
                    category_row = db.query(models.SourceCategory).filter(models.SourceCategory.source_category_id == slice_item.category_id).first()
                    if category_row:
                        category_row.last_sync_error = repr(exc)
                        category_row.sync_status = "待同步"
                        db.commit()
                break

            if first_total is None:
                first_total = total_count
            if not items:
                break
            signature = tuple(item["source_item_id"] for item in items)
            if signature in seen_signatures:
                break
            seen_signatures.add(signature)

            with SessionLocal() as db:
                source = db.get(models.TrustedSource, source_id)
                category_row = (
                    db.query(models.SourceCategory)
                    .filter(models.SourceCategory.source_id == source_id, models.SourceCategory.source_category_id == slice_item.category_id)
                    .first()
                )
                if category_row is not None:
                    category_row.last_synced_page = page_index + 1
                    category_row.resource_count = total_count or category_row.resource_count

                for item in items:
                    exists = (
                        db.query(models.StandardResource)
                        .filter(models.StandardResource.source_id == source_id, models.StandardResource.source_book_id == item["source_item_id"])
                        .first()
                    )
                    if exists is not None:
                        skipped += 1
                        continue
                    summary = f"SPC高级搜索切片：{slice_item.category} {slice_item.field}:{slice_item.token}\n详情页：{item.get('detail_url') or ''}"
                    detail_hash = _detail_hash(item)
                    resource, was_created = _upsert_resource(
                        db,
                        source,
                        item["source_item_id"],
                        {
                            "standard_no": item["standard_no"],
                            "source_status_raw": item.get("source_status"),
                            "standard_name": item.get("standard_name") or item["standard_no"],
                            "resource_type": CATEGORY_LABELS.get(slice_item.category, (slice_item.category,))[0],
                            "source_status": item.get("source_status"),
                            "system_status": _system_status(item.get("source_status")),
                            "publish_date": item.get("publish_date"),
                            "effective_date": item.get("effective_date"),
                            "summary": summary,
                            "source_category_path": category_row.category_path if category_row else None,
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
                            evidence_note="SPC高级搜索列表快照入库。",
                        )
                    )
                pages += 1
                db.commit()
            if delay > 0:
                time.sleep(delay)

    with SessionLocal() as db:
        category_row = (
            db.query(models.SourceCategory)
            .filter(models.SourceCategory.source_id == source_id, models.SourceCategory.source_category_id == slice_item.category_id)
            .first()
        )
        if category_row is not None:
            category_row.last_sync_finished_at = _now()
            category_row.last_synced_at = category_row.last_sync_finished_at
            total_pages = (category_row.resource_count + 9) // 10 if category_row.resource_count else None
            category_row.sync_status = (
                "已同步"
                if not errors and total_pages and (category_row.last_synced_page or 0) >= total_pages
                else "待同步"
            )
            db.commit()

    payload = {
        "slice": slice_item.__dict__,
        "pages": pages,
        "created": created,
        "skipped": skipped,
        "updated": updated,
        "errors": errors,
        "total": first_total,
    }
    print("spc_adv_slice_result " + json.dumps(payload, ensure_ascii=False, default=str), flush=True)
    return payload


def build_slices(categories: list[str]) -> list[AdvancedSlice]:
    slices: list[AdvancedSlice] = []
    if "QT" in categories:
        qt_prefixes = [
            "AQ", "BB", "CB", "CH", "CJ", "CY", "DA", "DB", "DL", "DZ", "EJ", "FZ", "GA", "GBZ", "HG", "HJ",
            "JB", "JC", "JG", "JR", "JT", "JY", "LB", "LD", "LS", "LY", "MH", "MT", "MZ", "NB", "NY", "QB",
            "QC", "QJ", "QX", "RB", "SB", "SC", "SF", "SH", "SJ", "SL", "SN", "SY", "TB", "TY", "WH", "WS",
            "XB", "XF", "YB", "YC", "YD", "YS", "YY", "YZ", "ZY",
        ]
        slices.extend(AdvancedSlice("QT", item) for item in qt_prefixes)
    if "DFBZ" in categories:
        region_codes = [11, 12, 13, 14, 15, 21, 22, 23, 31, 32, 33, 34, 35, 36, 37, 41, 42, 43, 44, 45, 46, 50, 51, 52, 53, 54, 61, 62, 63, 64, 65]
        for code in region_codes:
            slices.extend(AdvancedSlice("DFBZ", f"DB{code}/T {digit}") for digit in "0123456789")
            slices.extend(AdvancedSlice("DFBZ", f"DB{code} {digit}") for digit in "0123456789")
        slices.extend(AdvancedSlice("DFBZ", f"DB{code}") for code in region_codes)
    if "TC" in categories:
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        slices.extend(AdvancedSlice("TC", f"T/{left}{right}") for left in letters for right in letters)
        slices.extend(AdvancedSlice("TC", f"T/{digit}") for digit in "0123456789")
        slices.extend(AdvancedSlice("TC", letter) for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    if "QYBZ" in categories:
        slices.extend(AdvancedSlice("QYBZ", f"Q/{digit}") for digit in "0123456789")
        slices.extend(AdvancedSlice("QYBZ", f"Q/{letter}") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        slices.append(AdvancedSlice("QYBZ", "Q/"))
    if "CN" in categories:
        slices.extend(AdvancedSlice("CN", f"GB/T {digit}") for digit in "0123456789")
        slices.extend(AdvancedSlice("CN", f"GB {digit}") for digit in "0123456789")
        slices.extend([AdvancedSlice("CN", "GB/Z"), AdvancedSlice("CN", "GBJ")])
    if "JJ" in categories:
        slices.extend(AdvancedSlice("JJ", item) for item in ["JJF", "JJG", "JJGD", "JJFFZ", "JJFSH", "JJFYC", "JJGYC"])
    return slices


def interleave_by_category(slices: list[AdvancedSlice]) -> list[AdvancedSlice]:
    buckets: dict[str, list[AdvancedSlice]] = {}
    category_order: list[str] = []
    for item in slices:
        if item.category not in buckets:
            buckets[item.category] = []
            category_order.append(item.category)
        buckets[item.category].append(item)

    ordered: list[AdvancedSlice] = []
    index = 0
    while True:
        added = False
        for category in category_order:
            bucket = buckets[category]
            if index < len(bucket):
                ordered.append(bucket[index])
                added = True
        if not added:
            return ordered
        index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync SPC metadata through advanced-search prefix slices.")
    parser.add_argument("--categories", nargs="+", default=["QT", "DFBZ", "TC", "QYBZ", "CN", "JJ"])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--pages", type=int, default=200)
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--only", nargs="*", help="Optional prefix allow-list.")
    args = parser.parse_args()

    source_id = _source_id()
    slices = build_slices([item.upper() for item in args.categories])
    if args.only:
        allow = set(args.only)
        slices = [item for item in slices if item.token in allow or item.category in allow]
    slices = interleave_by_category(slices)
    plan = {
        "total": len(slices),
        "by_category": {category: sum(1 for item in slices if item.category == category) for category in sorted({item.category for item in slices})},
        "sample": [item.__dict__ for item in slices[:20]],
    }
    print("spc_adv_slice_plan " + json.dumps(plan, ensure_ascii=False), flush=True)

    errors = 0
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(slices) or 1))) as executor:
        futures = [
            executor.submit(sync_slice, item, source_id=source_id, max_pages=args.pages, delay=args.delay, retries=args.retries)
            for item in slices
        ]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                errors += 1
                print("spc_adv_slice_error " + json.dumps({"error": repr(exc)}, ensure_ascii=False), flush=True)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
