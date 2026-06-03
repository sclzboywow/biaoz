from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.download_service import DownloadedContent, archive_downloaded_content  # noqa: E402
from app.samr_std_sync import (  # noqa: E402
    BASE_URL,
    _detail_url,
    _download_url,
    _http_error_message,
    _is_access_limited,
    _online_url,
    _open_info_url,
    _review_url,
    _text,
    _upsert_resource,
)
from app.standard_number import normalize_standard_no  # noqa: E402
from app.settings_store import get_int_setting  # noqa: E402
from app.status_calibration import attach_change_logs_to_documents, calibrate_resource_status  # noqa: E402
from app.storage import check_storage_root  # noqa: E402


SOURCE_NAME = "国家标准信息公共服务平台（全量）"
ADAPTER_KEY = "samr_gb_all_public"
CATEGORY_ID = "gb_all"
CATEGORY_NAME = "国家标准（全量）"
CATEGORY_PATH = "国家标准信息公共服务平台（全量） / 国家标准"
SOURCE_URL = f"{BASE_URL}/gb"
PAGE_SIZE = int(os.getenv("GUOJIA_PAGE_SIZE", "200"))
LEGACY_CURSOR_PAGE_SIZE = int(os.getenv("GUOJIA_LEGACY_CURSOR_PAGE_SIZE", "50"))
REQUEST_DELAY_SECONDS = float(os.getenv("GUOJIA_REQUEST_DELAY_SECONDS", "1"))
RATE_LIMIT_COOLDOWN_SECONDS = int(os.getenv("GUOJIA_RATE_LIMIT_COOLDOWN_SECONDS", "1800"))
STALE_SYNC_SECONDS = int(os.getenv("GUOJIA_STALE_SYNC_SECONDS", "600"))
TRANSIENT_RETRY_ATTEMPTS = int(os.getenv("GUOJIA_TRANSIENT_RETRY_ATTEMPTS", "2"))
TRANSIENT_RETRY_DELAY_SECONDS = float(os.getenv("GUOJIA_TRANSIENT_RETRY_DELAY_SECONDS", "8"))
PID_FILE = ROOT / "logs" / "guojiabiaozhun-sync.pid"
RATE_LIMIT_TOKENS = ("访问过于频繁", "401", "Unauthorized", "Too Many Requests", "429")
CURSOR_PREFIX = "cursor:"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _log(message: str) -> None:
    print(f"[{_now()}] {message}", flush=True)


def _delay() -> None:
    if REQUEST_DELAY_SECONDS > 0:
        time.sleep(REQUEST_DELAY_SECONDS)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_rate_limited_status(exc: httpx.HTTPStatusError) -> bool:
    status_code = exc.response.status_code
    return status_code in {401, 429} or _is_access_limited(exc)


def _is_transient_status(exc: httpx.HTTPStatusError) -> bool:
    return exc.response.status_code in {502, 503, 504}


def _retry_delay(attempt: int) -> None:
    delay = TRANSIENT_RETRY_DELAY_SECONDS * max(1, attempt)
    if delay > 0:
        time.sleep(delay)


def _cursor_state(category: models.SourceCategory) -> tuple[int, int]:
    raw = category.last_seen_book_ids_hash or ""
    if raw.startswith(CURSOR_PREFIX):
        values: dict[str, int] = {}
        for part in raw[len(CURSOR_PREFIX) :].split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            try:
                values[key] = int(value)
            except ValueError:
                pass
        page_size = max(1, values.get("page_size") or PAGE_SIZE)
        completed_items = max(0, values.get("completed_items") or ((category.last_synced_page or 0) * page_size))
        return page_size, completed_items
    return LEGACY_CURSOR_PAGE_SIZE, max(0, (category.last_synced_page or 0) * LEGACY_CURSOR_PAGE_SIZE)


def _write_cursor(category: models.SourceCategory, completed_items: int) -> None:
    category.last_seen_book_ids_hash = f"{CURSOR_PREFIX}page_size={PAGE_SIZE};completed_items={max(0, completed_items)}"


def _client(timeout_seconds: int = 30) -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=timeout_seconds,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
        },
    )


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    return f'"{pid}"' in completed.stdout or f",{pid}," in completed.stdout


def _claim_pidfile(pid_file: Path) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except Exception:
            existing_pid = 0
        if _pid_running(existing_pid):
            raise SystemExit(f"国家标准全量库同步已在运行：pid={existing_pid}")
    pid_file.write_text(str(os.getpid()), encoding="utf-8")


def _release_pidfile(pid_file: Path) -> None:
    try:
        if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
            pid_file.unlink()
    except Exception:
        pass


def ensure_source_and_category(db) -> tuple[models.TrustedSource, models.SourceCategory]:
    source = db.query(models.TrustedSource).filter(models.TrustedSource.source_name == SOURCE_NAME).first()
    if source is None:
        source = models.TrustedSource(
            source_name=SOURCE_NAME,
            base_url=SOURCE_URL,
            trust_level="A",
            trust_score=100,
            source_type="国家标准权威信息源",
            adapter_key=ADAPTER_KEY,
            capabilities="list,detail,status,category,online,download,change,file",
            is_status_authority=True,
            crawl_mode="公开检索接口 + 详情接口 + 官方全文入口 + PDF严格归档",
            crawl_frequency="manual",
            enabled=True,
            remark="来自根目录 guojiabiaozhun.py 的全量国家标准库入库流程；真实文件仅在确认为 PDF 时归档。",
        )
        db.add(source)
        db.flush()
    else:
        source.adapter_key = source.adapter_key or ADAPTER_KEY
        source.base_url = source.base_url or SOURCE_URL
        source.capabilities = source.capabilities or "list,detail,status,category,online,download,change,file"

    category = (
        db.query(models.SourceCategory)
        .filter(
            models.SourceCategory.source_id == source.id,
            models.SourceCategory.source_category_id == CATEGORY_ID,
        )
        .first()
    )
    if category is None:
        category = models.SourceCategory(
            source_id=source.id,
            source_category_id=CATEGORY_ID,
            category_name=CATEGORY_NAME,
            category_path=CATEGORY_PATH,
            source_url=SOURCE_URL,
            sync_status="待同步",
        )
        db.add(category)
        db.flush()
    else:
        category.category_name = CATEGORY_NAME
        category.category_path = CATEGORY_PATH
        category.source_url = SOURCE_URL
    db.commit()
    return source, category


def fetch_list_page(client: httpx.Client, page_number: int) -> dict[str, Any]:
    response = client.get(
        f"{BASE_URL}/gb/search/gbQueryPage",
        params={
            "searchText": "",
            "ics": "",
            "state": "",
            "ISSUE_DATE": "",
            "sortOrder": "asc",
            "pageSize": str(PAGE_SIZE),
            "pageNumber": str(page_number),
            "_": str(int(time.time() * 1000)),
        },
        headers={"Referer": f"{BASE_URL}/gb"},
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise RuntimeError(f"列表接口返回非 JSON：{content_type} {response.text[:120]}")
    return response.json()


def fetch_detail(client: httpx.Client, item_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.get(
        f"{BASE_URL}/gb/search/gbDetailInfo",
        params={"id": item_id},
        headers={"Referer": _detail_url(item_id)},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {}, payload
    gb = data.get("gb")
    return gb if isinstance(gb, dict) else {}, payload


def fetch_list_page(client: httpx.Client, page_number: int) -> dict[str, Any]:
    for attempt in range(1, TRANSIENT_RETRY_ATTEMPTS + 2):
        try:
            response = client.get(
                f"{BASE_URL}/gb/search/gbQueryPage",
                params={
                    "searchText": "",
                    "ics": "",
                    "state": "",
                    "ISSUE_DATE": "",
                    "sortOrder": "asc",
                    "pageSize": str(PAGE_SIZE),
                    "pageNumber": str(page_number),
                    "_": str(int(time.time() * 1000)),
                },
                headers={"Referer": f"{BASE_URL}/gb"},
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type.lower():
                raise RuntimeError(f"List API returned non-JSON: {content_type} {response.text[:120]}")
            return response.json()
        except httpx.HTTPStatusError as exc:
            if _is_rate_limited_status(exc) or not _is_transient_status(exc) or attempt > TRANSIENT_RETRY_ATTEMPTS:
                raise
            _log(f"list page {page_number} transient {_http_error_message(exc)!r}; retry {attempt}/{TRANSIENT_RETRY_ATTEMPTS}")
            _retry_delay(attempt)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            if attempt > TRANSIENT_RETRY_ATTEMPTS:
                raise
            _log(f"list page {page_number} transient {exc!r}; retry {attempt}/{TRANSIENT_RETRY_ATTEMPTS}")
            _retry_delay(attempt)
    raise RuntimeError(f"List API retry failed: page={page_number}")


def fetch_detail(client: httpx.Client, item_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for attempt in range(1, TRANSIENT_RETRY_ATTEMPTS + 2):
        try:
            response = client.get(
                f"{BASE_URL}/gb/search/gbDetailInfo",
                params={"id": item_id},
                headers={"Referer": _detail_url(item_id)},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                return {}, payload
            gb = data.get("gb")
            return gb if isinstance(gb, dict) else {}, payload
        except httpx.HTTPStatusError as exc:
            if _is_rate_limited_status(exc) or not _is_transient_status(exc) or attempt > TRANSIENT_RETRY_ATTEMPTS:
                raise
            _log(f"detail {item_id} transient {_http_error_message(exc)!r}; retry {attempt}/{TRANSIENT_RETRY_ATTEMPTS}")
            _retry_delay(attempt)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            if attempt > TRANSIENT_RETRY_ATTEMPTS:
                raise
            _log(f"detail {item_id} transient {exc!r}; retry {attempt}/{TRANSIENT_RETRY_ATTEMPTS}")
            _retry_delay(attempt)
    raise RuntimeError(f"Detail API retry failed: id={item_id}")


def official_links(row: dict[str, Any], item_id: str) -> dict[str, str]:
    links = {"std_detail": _detail_url(item_id)}
    hcno = _text(row.get("OPEN_HASH_CODE"))
    if hcno:
        links.update(
            {
                "openstd_detail": _open_info_url(hcno),
                "online_preview": _online_url(hcno),
                "download_page": _download_url(hcno),
                "feedback": _review_url(hcno),
            }
        )
    return links


def _create_or_get_url_source(db, url: str, resource: models.StandardResource) -> models.UrlSource:
    source = db.query(models.UrlSource).filter(models.UrlSource.url == url).first()
    if source:
        return source
    source = models.UrlSource(
        url=url,
        source_name=resource.standard_name or resource.standard_no or url,
        source_unit=SOURCE_NAME,
        source_type="官方标准PDF",
        category="国家标准",
        check_frequency="manual",
        status=models.SourceStatus.normal.value,
        remark=f"standard_no={resource.standard_no or ''}; standard_resource_id={resource.id}; 来源={SOURCE_NAME}",
    )
    db.add(source)
    db.flush()
    return source


def _canonical_resource(
    db,
    source: models.TrustedSource,
    row: dict[str, Any],
) -> models.StandardResource | None:
    item_id = _text(row.get("id"))
    if item_id:
        existing = (
            db.query(models.StandardResource)
            .filter(
                models.StandardResource.source_id == source.id,
                models.StandardResource.source_book_id == item_id,
            )
            .first()
        )
        if existing:
            return existing

    standard_no = _text(row.get("C_STD_CODE")) or _text(row.get("STD_CODE"))
    normalized = normalize_standard_no(standard_no).normalized
    if normalized:
        return (
            db.query(models.StandardResource)
            .filter(
                models.StandardResource.source_id == source.id,
                models.StandardResource.normalized_standard_no == normalized,
            )
            .order_by(models.StandardResource.id)
            .first()
        )
    return None


def upsert_deduped_resource(
    db,
    source: models.TrustedSource,
    row: dict[str, Any],
    detail_payload: dict[str, Any] | None,
) -> tuple[models.StandardResource, bool]:
    existing = _canonical_resource(db, source, row)
    if existing and _text(row.get("id")) and existing.source_book_id != _text(row.get("id")):
        existing.source_book_id = _text(row.get("id"))
        db.flush()
    before_id = existing.id if existing else None
    resource, created = _upsert_resource(db, source, row, detail_payload)
    if before_id and resource.id != before_id:
        resource.source_book_id = f"duplicate:{resource.source_book_id or resource.id}"
        db.flush()
        existing = db.get(models.StandardResource, before_id)
        existing.source_book_id = _text(row.get("id")) or existing.source_book_id
        resource, created = _upsert_resource(db, source, row, detail_payload)
    return resource, created


def try_archive_pdf(db, client: httpx.Client, resource: models.StandardResource, row: dict[str, Any]) -> dict[str, int | str | None]:
    hcno = _text(row.get("OPEN_HASH_CODE"))
    if not hcno:
        return {"download_attempted": 0, "download_archived": 0, "download_skipped": 0, "skip_reason": "no OPEN_HASH_CODE"}
    url = _download_url(hcno)
    response = client.get(
        url,
        headers={
            "Accept": "application/pdf,*/*",
            "Referer": _online_url(hcno),
            "X-Requested-With": "",
        },
    )
    content_type = response.headers.get("content-type") or ""
    if response.status_code >= 400:
        return {
            "download_attempted": 1,
            "download_archived": 0,
            "download_skipped": 1,
            "skip_reason": f"HTTP {response.status_code}",
        }
    if not response.content.startswith(b"%PDF"):
        return {
            "download_attempted": 1,
            "download_archived": 0,
            "download_skipped": 1,
            "skip_reason": f"not pdf: {content_type or 'unknown'}",
        }

    url_source = _create_or_get_url_source(db, url, resource)
    result = archive_downloaded_content(
        db,
        url_source,
        check_storage_root(db, Path(os.getenv("STORAGE_ROOT", "G:/data/standard-docs"))).root,
        DownloadedContent(
            status_code=response.status_code,
            url=str(response.url),
            content=response.content,
            content_type=content_type,
            content_disposition=response.headers.get("content-disposition"),
        ),
    )
    return {
        "download_attempted": 1,
        "download_archived": 1 if result.ok else 0,
        "download_skipped": 0 if result.ok else 1,
        "skip_reason": None if result.ok else result.message,
    }


def _snapshot(db, source: models.TrustedSource, category: models.SourceCategory) -> dict[str, Any]:
    resources = db.query(func.count(models.StandardResource.id)).filter(models.StandardResource.source_id == source.id).scalar()
    details = (
        db.query(func.count(models.StandardDetail.id))
        .join(models.StandardResource, models.StandardDetail.standard_resource_id == models.StandardResource.id)
        .filter(models.StandardResource.source_id == source.id)
        .scalar()
    )
    online_links = (
        db.query(func.count(models.StandardResource.id))
        .filter(
            models.StandardResource.source_id == source.id,
            models.StandardResource.pdf_trial_url.isnot(None),
            models.StandardResource.pdf_trial_url != "",
        )
        .scalar()
    )
    return {
        "page": category.last_synced_page or 0,
        "status": category.sync_status,
        "error": category.last_sync_error,
        "remote_total": category.resource_count or 0,
        "resources": resources or 0,
        "details": details or 0,
        "online_links": online_links or 0,
    }


def sync_one_page(include_files: bool) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "pages": 0,
        "items": 0,
        "created": 0,
        "updated": 0,
        "details": 0,
        "errors": 0,
        "download_attempted": 0,
        "download_archived": 0,
        "download_skipped": 0,
        "matches": 0,
        "linked_change_logs": 0,
    }
    with SessionLocal() as db:
        source, category = ensure_source_and_category(db)
        _cursor_page_size, completed_items = _cursor_state(category)
        if _cursor_page_size != PAGE_SIZE:
            completed_items = max(0, completed_items - max(_cursor_page_size, PAGE_SIZE))
        last_started = _as_utc(category.last_sync_started_at)
        last_finished = _as_utc(category.last_sync_finished_at)
        if (
            last_started
            and (last_finished is None or last_finished < last_started)
            and (datetime.now(UTC) - last_started).total_seconds() > STALE_SYNC_SECONDS
        ):
            completed_items = max(0, completed_items - _cursor_page_size)
            category.last_synced_page = completed_items // PAGE_SIZE
            _write_cursor(category, completed_items)
            category.last_sync_error = "previous sync interrupted; retrying the last page"
            db.commit()

        start_page = (completed_items // PAGE_SIZE) + 1
        category.sync_status = "同步中"
        category.last_sync_started_at = datetime.now(UTC)
        category.last_sync_error = None
        db.commit()

        page_error: str | None = None
        page_complete = False
        access_limited = False
        with _client(get_int_setting(db, "download_timeout_seconds", 30)) as client:
            try:
                page = fetch_list_page(client, start_page)
                rows = page.get("rows") if isinstance(page, dict) else []
                if not isinstance(rows, list):
                    rows = []
                category.resource_count = int(page.get("total") or 0)
            except httpx.HTTPStatusError as exc:
                stats["errors"] += 1
                page_error = _http_error_message(exc)
                category.last_sync_error = page_error
                access_limited = _is_rate_limited_status(exc)
                rows = []
            except Exception as exc:
                stats["errors"] += 1
                page_error = str(exc)
                category.last_sync_error = page_error
                rows = []

            if rows:
                _delay()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                item_id = _text(row.get("id"))
                if not item_id:
                    stats["errors"] += 1
                    continue

                detail_payload: dict[str, Any] | None = None
                try:
                    detail_row, detail_payload = fetch_detail(client, item_id)
                    _delay()
                    if detail_row:
                        row.update(detail_row)
                    stats["details"] += 1
                except httpx.HTTPStatusError as exc:
                    stats["errors"] += 1
                    page_error = _http_error_message(exc)
                    category.last_sync_error = page_error
                    if _is_rate_limited_status(exc):
                        access_limited = True
                        break
                except Exception as exc:
                    stats["errors"] += 1
                    category.last_sync_error = str(exc)

                try:
                    resource, created = upsert_deduped_resource(db, source, row, detail_payload or row)
                    stats["created" if created else "updated"] += 1
                    stats["items"] += 1
                    calibration = calibrate_resource_status(db, resource)
                    stats["matches"] += calibration["matches"]
                    stats["linked_change_logs"] += attach_change_logs_to_documents(db, resource)
                    if include_files:
                        file_result = try_archive_pdf(db, client, resource, row)
                        for key in ("download_attempted", "download_archived", "download_skipped"):
                            stats[key] += int(file_result.get(key) or 0)
                        if file_result.get("download_attempted"):
                            _delay()
                except Exception as exc:
                    stats["errors"] += 1
                    category.last_sync_error = str(exc)
                db.commit()

            page_complete = (not access_limited) and (page_error is None or bool(rows))
            if page_complete:
                completed_items = max(completed_items, start_page * PAGE_SIZE)
                category.last_synced_page = start_page
                _write_cursor(category, completed_items)
                stats["pages"] = 1

        total_pages = max(1, ((category.resource_count or 0) + PAGE_SIZE - 1) // PAGE_SIZE)
        completed = (category.last_synced_page or 0) >= total_pages
        category.last_sync_finished_at = datetime.now(UTC)
        category.last_synced_at = category.last_sync_finished_at
        category.sync_status = "同步失败" if stats["errors"] else ("已同步" if completed else "待同步")
        category.last_sync_error = category.last_sync_error or page_error
        db.commit()
        stats["snapshot"] = _snapshot(db, source, category)
    return stats


def run(args: argparse.Namespace) -> int:
    _claim_pidfile(Path(args.pid_file))
    synced_pages = 0
    try:
        _log(
            "guojiabiaozhun sync started "
            f"page_size={PAGE_SIZE} request_delay={REQUEST_DELAY_SECONDS}s "
            f"interval={args.interval_seconds}s transient_retries={TRANSIENT_RETRY_ATTEMPTS} "
            f"cooldown={args.cooldown_seconds}s include_files={args.include_files}"
        )
        while True:
            stats = sync_one_page(include_files=args.include_files)
            synced_pages += int(stats.get("pages") or 0)
            _log("sync_result " + json.dumps(stats, ensure_ascii=False, default=str))
            snapshot = stats.get("snapshot") or {}
            error = str(snapshot.get("error") or "")
            if any(token in error for token in ("访问过于频繁", "401", "Unauthorized")):
                _log(f"access limit detected; sleeping {args.cooldown_seconds}s")
                time.sleep(args.cooldown_seconds)
            if args.once or (args.max_pages and synced_pages >= args.max_pages):
                return 0
            if snapshot.get("status") == "已同步":
                _log("all pages completed; exiting")
                return 0
            time.sleep(args.interval_seconds)
    finally:
        _release_pidfile(Path(args.pid_file))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync guojiabiaozhun.py national standards library into database.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--interval-seconds", type=int, default=180)
    parser.add_argument("--cooldown-seconds", type=int, default=RATE_LIMIT_COOLDOWN_SECONDS)
    parser.add_argument("--include-files", action="store_true", help="Try to archive only verified PDF responses.")
    parser.add_argument("--pid-file", default=str(PID_FILE))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
