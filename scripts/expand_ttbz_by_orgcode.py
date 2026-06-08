from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import models  # noqa: E402
from app import samr_public_adapters  # noqa: F401,E402
from app.database import SessionLocal  # noqa: E402
from app.samr_public_adapters import _parse_date, _text, _detail_hash, _limit, _system_status, _upsert_resource  # noqa: E402
from app.status_calibration import attach_change_logs_to_documents, calibrate_resource_status  # noqa: E402

import httpx  # noqa: E402


ORG_CODE_RE = re.compile(r"^T/([A-Z0-9]+)")


def org_codes_from_db(source_id: int) -> list[str]:
    with SessionLocal() as db:
        rows = (
            db.query(models.StandardResource.standard_no)
            .filter(models.StandardResource.source_id == source_id, models.StandardResource.standard_no.isnot(None))
            .all()
        )
    codes = set()
    for (standard_no,) in rows:
        match = ORG_CODE_RE.match(standard_no or "")
        if match:
            codes.add(match.group(1))
    return sorted(codes)


def fetch_page(client: httpx.Client, params: dict[str, Any], page: int, page_size: int) -> dict[str, Any]:
    response = client.post(
        "https://www.ttbz.org.cn/cms-proxy/ms/portal/standardInfo/getPortalStandardList",
        data={"pageNo": page, "pageSize": page_size, **params},
    )
    response.raise_for_status()
    return response.json()


def upsert_row(db, source, row: dict[str, Any], slice_key: str) -> bool:
    item_id = _text(row.get("standardUniqueId") or row.get("id"))
    if not item_id:
        return False
    standard_no = _text(row.get("standardNo"))
    source_status = _text(row.get("standardStatusName") or row.get("statusName"))
    detail_url = f"https://www.ttbz.org.cn/standardDetail/{item_id}.html"
    summary = "\n".join(
        part
        for part in [
            f"社会团体：{_text(row.get('organName'))}" if _text(row.get("organName")) else "",
            f"组织代码：{_text(row.get('organCode'))}" if _text(row.get("organCode")) else "",
            f"ICS：{_text(row.get('icsl1Name'))}" if _text(row.get("icsl1Name")) else "",
            f"CCS：{_text(row.get('ccsl1Name'))}" if _text(row.get("ccsl1Name")) else "",
            f"是否公开：{_text(row.get('isOpenName'))}" if _text(row.get("isOpenName")) else "",
            f"切片：{slice_key}",
        ]
        if part
    )
    _, created = _upsert_resource(
        db,
        source,
        item_id,
        {
            "standard_no": standard_no,
            "source_status_raw": source_status,
            "standard_name": _text(row.get("standardTitleCn")) or standard_no or item_id,
            "resource_type": "团体标准",
            "source_status": source_status,
            "system_status": _system_status(source_status),
            "publish_date": _parse_date(row.get("publishDate") or row.get("filePublishDate")),
            "effective_date": _parse_date(row.get("implementDate")),
            "abolish_date": _parse_date(row.get("abolishDate")),
            "chief_editor_unit": _limit(_text(row.get("organName")), 500),
            "summary": summary,
            "keywords": _text(row.get("icsl1Name") or row.get("ccsl1Name")),
            "source_category_path": "全国标准信息公共服务平台 / 团体标准信息平台",
            "detail_url": detail_url,
            "detail_hash": _detail_hash(row),
        },
        evidence_summary=summary,
    )
    return created


def sync_slice(db, source, client: httpx.Client, params: dict[str, Any], max_pages: int, page_size: int, delay: float) -> tuple[int, int, int, int]:
    pages = items = created_count = total = 0
    for page in range(1, max_pages + 1):
        payload = fetch_page(client, params, page, page_size)
        data = payload.get("data") if isinstance(payload, dict) else {}
        rows = data.get("rows") if isinstance(data, dict) else []
        total = int(data.get("total") or total or 0) if isinstance(data, dict) else total
        if not rows:
            break
        pages += 1
        for row in rows:
            if not isinstance(row, dict):
                continue
            resource_created = upsert_row(db, source, row, "&".join(f"{k}={v}" for k, v in params.items()))
            created_count += 1 if resource_created else 0
            items += 1
        db.commit()
        if page * page_size >= total:
            break
        time.sleep(delay)
    return pages, items, created_count, total


def main() -> int:
    parser = argparse.ArgumentParser(description="Expand TTBZ coverage by organization code and numeric shards.")
    parser.add_argument("--source-id", type=int, default=6)
    parser.add_argument("--limit-orgs", type=int, default=0)
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()

    org_codes = org_codes_from_db(args.source_id)
    if args.limit_orgs:
        org_codes = org_codes[: args.limit_orgs]
    print(f"org_codes={len(org_codes)}")

    totals = {"pages": 0, "items": 0, "created": 0, "orgs": 0, "shards": 0}
    with SessionLocal() as db:
        source = db.get(models.TrustedSource, args.source_id)
        if source is None:
            raise SystemExit(f"source not found: {args.source_id}")
        category = (
            db.query(models.SourceCategory)
            .filter(models.SourceCategory.source_id == args.source_id, models.SourceCategory.source_category_id == "group_standard")
            .first()
        )
        if category:
            category.sync_status = "同步中"
            category.last_sync_error = None
            db.commit()
        with httpx.Client(
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://www.ttbz.org.cn/standard.html"},
        ) as client:
            for org_code in org_codes:
                totals["orgs"] += 1
                pages, items, created, total = sync_slice(
                    db, source, client, {"organCode": org_code}, args.max_pages, args.page_size, args.delay
                )
                totals["pages"] += pages
                totals["items"] += items
                totals["created"] += created
                if total >= 100:
                    for digit in "0123456789":
                        totals["shards"] += 1
                        pages, items, created, _ = sync_slice(
                            db,
                            source,
                            client,
                            {"standardNo": f"T/{org_code} {digit}"},
                            args.max_pages,
                            args.page_size,
                            args.delay,
                        )
                        totals["pages"] += pages
                        totals["items"] += items
                        totals["created"] += created
                if totals["orgs"] % 50 == 0:
                    print(f"progress {totals}", flush=True)
            stored_count = db.query(models.StandardResource).filter(models.StandardResource.source_id == args.source_id).count()
            if category:
                category.resource_count = stored_count
                category.last_synced_at = category.last_sync_finished_at = samr_public_adapters._now()
                category.sync_status = "已同步"
            db.commit()
    print(f"done {totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
