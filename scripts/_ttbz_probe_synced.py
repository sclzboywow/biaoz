from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

import httpx
from sqlalchemy import text

from app.database import SessionLocal
from app.http_proxy import resolve_ttbz_http_proxy
from app.ttbz_download import (
    TtbzDownloadError,
    TtbzDownloadUnavailableError,
    download_ttbz_pdf,
    extract_ttbz_unique_id,
)

ADAPTER_KEY = "samr_group_standard_public"

SYNCED_WITH_FILE_SQL = """
SELECT sr.id, sr.standard_no, sr.source_book_id, sr.detail_url, sr.sync_status,
       dv.id AS version_id, dv.file_path
FROM standard_resources sr
JOIN url_sources us ON us.url = sr.detail_url
JOIN document_versions dv ON dv.url_source_id = us.id AND dv.is_current = true
WHERE sr.source_id = :source_id
  AND sr.sync_status = '已同步'
  AND dv.file_path IS NOT NULL
  AND btrim(dv.file_path) <> ''
ORDER BY sr.id DESC
LIMIT :limit
"""

CROSS_FILE_SQL = """
SELECT t.id, t.standard_no, t.source_book_id, t.detail_url, t.sync_status,
       dv.id AS version_id, dv.file_path
FROM standard_resources t
JOIN standard_resources o ON o.standard_no = t.standard_no AND o.source_id <> t.source_id
JOIN url_sources us ON us.url = o.detail_url
JOIN document_versions dv ON dv.url_source_id = us.id AND dv.is_current = true
WHERE t.source_id = :source_id
  AND btrim(dv.file_path) <> ''
ORDER BY t.id DESC
LIMIT :limit
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe TTBZ download for DB entries that already have local files.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--http-proxy", default="")
    parser.add_argument("--resource-id", type=int, action="append")
    parser.add_argument(
        "--mode",
        choices=("synced-with-file", "cross-file", "live-open"),
        default="synced-with-file",
        help="synced-with-file: ttbz rows with local document_versions; cross-file: same standard_no has file in other source; live-open: ttbz API isOpen=1 list",
    )
    args = parser.parse_args()

    proxy = (args.http_proxy or "").strip() or resolve_ttbz_http_proxy()
    with SessionLocal() as db:
        source_id = db.execute(
            text("SELECT id FROM trusted_sources WHERE adapter_key = :key"),
            {"key": ADAPTER_KEY},
        ).scalar()
        if not source_id:
            print("source_not_found")
            return 1

        if args.mode == "cross-file":
            rows = db.execute(
                text(CROSS_FILE_SQL),
                {"source_id": source_id, "limit": max(args.limit, 1)},
            ).all()
        elif args.mode == "live-open":
            rows = []
        elif args.resource_id:
            rows = db.execute(
                text(
                    """
                    SELECT sr.id, sr.standard_no, sr.source_book_id, sr.detail_url, sr.sync_status,
                           dv.id AS version_id, dv.file_path
                    FROM standard_resources sr
                    LEFT JOIN url_sources us ON us.url = sr.detail_url
                    LEFT JOIN document_versions dv ON dv.url_source_id = us.id AND dv.is_current = true
                    WHERE sr.id = ANY(:ids)
                    ORDER BY sr.id
                    """
                ),
                {"ids": args.resource_id},
            ).all()
        else:
            rows = db.execute(
                text(SYNCED_WITH_FILE_SQL),
                {"source_id": source_id, "limit": max(args.limit, 1)},
            ).all()

        total = db.execute(
            text(
                """
                SELECT COUNT(DISTINCT sr.id)
                FROM standard_resources sr
                JOIN url_sources us ON us.url = sr.detail_url
                JOIN document_versions dv ON dv.url_source_id = us.id AND dv.is_current = true
                WHERE sr.source_id = :source_id AND sr.sync_status = '已同步'
                """
            ),
            {"source_id": source_id},
        ).scalar()

    live_rows: list[dict] = []
    if args.mode == "live-open":
        kwargs = {"follow_redirects": True, "timeout": 60, "headers": {"User-Agent": "Mozilla/5.0", "Referer": "https://www.ttbz.org.cn/standard.html"}}
        if proxy:
            kwargs["proxy"] = proxy
        with httpx.Client(**kwargs) as client:
            payload = client.post(
                "https://www.ttbz.org.cn/cms-proxy/ms/portal/standardInfo/getPortalStandardList",
                data={"pageNo": 1, "pageSize": max(args.limit, 1), "isOpen": "1"},
            ).json()
            data = payload.get("data") if isinstance(payload, dict) else {}
            api_rows = (data.get("rows") or data.get("list") or []) if isinstance(data, dict) else []
            for item in api_rows[: args.limit]:
                if not isinstance(item, dict):
                    continue
                uid = str(item.get("standardUniqueId") or item.get("id") or "")
                if not uid:
                    continue
                live_rows.append(
                    {
                        "resource_id": None,
                        "standard_no": item.get("standardNo"),
                        "source_book_id": uid,
                        "detail_url": f"https://www.ttbz.org.cn/standardDetail/{uid}.html",
                        "sync_status": "live-open",
                        "version_id": None,
                        "file_path": None,
                        "is_open": item.get("isOpen"),
                    }
                )

    print(
        "ttbz_probe_plan "
        + json.dumps(
            {
                "mode": args.mode,
                "source_id": source_id,
                "total_synced_with_file": total,
                "probe_count": len(rows) if args.mode != "live-open" else len(live_rows),
                "proxy": proxy or None,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    ok = fail = 0
    kwargs = {"follow_redirects": True, "timeout": 60}
    if proxy:
        kwargs["proxy"] = proxy

    with httpx.Client(**kwargs) as client:
        iterable = live_rows if args.mode == "live-open" else rows
        for row in iterable:
            if args.mode == "live-open":
                rid = row["resource_id"]
                std_no = row["standard_no"]
                book_id = row["source_book_id"]
                detail_url = row["detail_url"]
                status = row["sync_status"]
                version_id = row["version_id"]
                file_path = row["file_path"]
            else:
                rid, std_no, book_id, detail_url, status, version_id, file_path = row
            uid = extract_ttbz_unique_id(detail_url, source_book_id=book_id)
            payload = {
                "resource_id": rid,
                "standard_no": std_no,
                "unique_id": uid,
                "sync_status": status,
                "version_id": version_id,
                "file_path": file_path,
            }
            if not uid:
                payload.update({"ok": False, "error": "missing_unique_id"})
                fail += 1
                print("ttbz_probe_result " + json.dumps(payload, ensure_ascii=False), flush=True)
                continue
            try:
                downloaded = download_ttbz_pdf(uid, detail_url=detail_url, client=client)
                payload.update(
                    {
                        "ok": True,
                        "bytes": len(downloaded.content),
                        "content_type": downloaded.content_type,
                        "is_pdf": downloaded.content.startswith(b"%PDF"),
                    }
                )
                ok += 1
            except TtbzDownloadUnavailableError as exc:
                payload.update({"ok": False, "unavailable": True, "error": repr(exc)})
                fail += 1
            except TtbzDownloadError as exc:
                payload.update({"ok": False, "error": repr(exc)})
                fail += 1
            except Exception as exc:
                payload.update({"ok": False, "error": repr(exc)})
                fail += 1
            print("ttbz_probe_result " + json.dumps(payload, ensure_ascii=False), flush=True)

    print("ttbz_probe_summary " + json.dumps({"ok": ok, "fail": fail, "total": len(rows)}, ensure_ascii=False), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
