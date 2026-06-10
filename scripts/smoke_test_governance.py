#!/usr/bin/env python3
"""Governance phase acceptance smoke test (DB schema + HTTP APIs).

Usage:
  backend/.venv/Scripts/python.exe scripts/smoke_test_governance.py
  backend/.venv/Scripts/python.exe scripts/smoke_test_governance.py --api-base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import inspect, text

from app.database import SessionLocal, engine

REQUIRED_TABLES = [
    "source_governance_runs",
    "source_record_candidates",
    "governance_decisions",
    "file_objects",
    "ocr_download_tasks",
    "process_audit_logs",
]

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "url_sources": [
        "host",
        "url_type",
        "file_ext",
        "is_official_domain",
        "is_cloud_drive",
        "is_probable_pdf",
        "is_probable_detail_page",
        "source_quality_score",
        "governance_status",
        "duplicate_group_key",
    ],
    "trusted_sources": [
        "source_role",
        "domain",
        "status_authority_weight",
        "fulltext_weight",
        "metadata_weight",
        "source_health_score",
        "governance_status",
    ],
    "alerts": [
        "dedupe_key",
        "repeat_count",
        "first_seen_at",
        "last_seen_at",
        "risk_level",
    ],
    "document_versions": [
        "file_object_id",
        "original_file_name",
    ],
}


def check_schema() -> list[str]:
    errors: list[str] = []
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table in REQUIRED_TABLES:
        if table not in tables:
            errors.append(f"missing table: {table}")
    for table, columns in REQUIRED_COLUMNS.items():
        if table not in tables:
            errors.append(f"missing table for column check: {table}")
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for col in columns:
            if col not in existing:
                errors.append(f"missing column: {table}.{col}")
    with SessionLocal() as db:
        row = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        if row != "20260610_0005":
            errors.append(f"alembic head mismatch: current={row!r}, expected='20260610_0005'")
    return errors


def _http_json(method: str, url: str, payload: dict | None = None, timeout: int = 120):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else {}


def check_http(api_base: str) -> list[str]:
    errors: list[str] = []
    base = api_base.rstrip("/")
    api = f"{base}/api/v1"

    def get(path: str):
        url = f"{api}{path}"
        try:
            status, data = _http_json("GET", url)
        except urllib.error.HTTPError as exc:
            errors.append(f"GET {path} -> {exc.code}: {exc.read()[:200]!r}")
            return None
        if status >= 400:
            errors.append(f"GET {path} -> {status}")
            return None
        return data

    def post(path: str, payload: dict):
        url = f"{api}{path}"
        try:
            status, data = _http_json("POST", url, payload)
        except urllib.error.HTTPError as exc:
            errors.append(f"POST {path} -> {exc.code}: {exc.read()[:200]!r}")
            return None
        if status >= 400:
            errors.append(f"POST {path} -> {status}")
            return None
        return data

    try:
        status, health = _http_json("GET", f"{base}/health")
        if status >= 400:
            errors.append(f"GET /health -> {status}")
        else:
            print(f"OK /health -> {health}")
    except Exception as exc:
        errors.append(f"GET /health failed: {exc}")
        return errors

    summary = get("/dashboard/governance-summary")
    if summary:
        print(f"OK governance-summary url_total={summary.get('url_total')}")

    profile = post("/source-governance/profile-url-sources", {"limit": 50, "dry_run": True, "only_ungoverned": True})
    if profile:
        print(f"OK profile-url-sources dry_run total={profile.get('total')} profiled={profile.get('profiled')}")

    decisions = post("/governance/run-decisions", {"limit": 50, "only_unprocessed": True, "dry_run": True})
    if decisions:
        print(f"OK run-decisions dry_run processed={decisions.get('processed')}")

    ocr = get("/ocr-tasks/summary")
    if ocr:
        print(f"OK ocr-tasks/summary pending_ocr={ocr.get('pending_ocr')}")

    files = get("/file-objects/summary")
    if files:
        print(f"OK file-objects/summary total={files.get('total')}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Governance acceptance smoke test")
    parser.add_argument("--api-base", default=os.getenv("API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--skip-http", action="store_true")
    args = parser.parse_args()

    print("== Schema checks ==")
    schema_errors = check_schema()
    if schema_errors:
        for err in schema_errors:
            print(f"FAIL {err}")
    else:
        print("OK schema tables/columns/alembic head")

    http_errors: list[str] = []
    if not args.skip_http:
        print("\n== HTTP checks ==")
        print("Tip: 404 on /api/v1/* usually means the running API process is outdated; restart backend after deploy.")
        try:
            http_errors = check_http(args.api_base)
        except Exception as exc:
            http_errors.append(f"HTTP connection failed: {exc}")
            print(f"FAIL {http_errors[-1]}")

    all_errors = schema_errors + http_errors
    print("\n== Summary ==")
    if all_errors:
        print(json.dumps({"ok": False, "errors": all_errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
