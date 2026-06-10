#!/usr/bin/env python3
"""Collect acceptance metrics for docs/governance_acceptance_report.md."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from sqlalchemy import func, inspect, select, text

from app.database import SessionLocal, engine
from app import models

SAMPLES = ("official_domains", "pdf_links", "cloud_drive", "commercial_sites")


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 300):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed


def schema_check() -> dict:
    required_tables = [
        "source_governance_runs",
        "source_record_candidates",
        "governance_decisions",
        "file_objects",
        "ocr_download_tasks",
        "process_audit_logs",
    ]
    required_columns = {
        "trusted_sources": [
            "source_role",
            "domain",
            "status_authority_weight",
            "fulltext_weight",
            "metadata_weight",
            "source_health_score",
            "governance_status",
        ],
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
        "document_versions": ["file_object_id", "original_file_name"],
        "alerts": ["dedupe_key", "repeat_count", "first_seen_at", "last_seen_at", "risk_level"],
    }
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing = [t for t in required_tables if t not in tables]
    missing_cols: list[str] = []
    for table, cols in required_columns.items():
        if table not in tables:
            missing_cols.append(f"{table}.*")
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for col in cols:
            if col not in existing:
                missing_cols.append(f"{table}.{col}")
    with SessionLocal() as db:
        alembic = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    return {
        "alembic": alembic,
        "missing_tables": missing,
        "missing_columns": missing_cols,
        "passed": not missing and not missing_cols and alembic == "20260610_0005",
    }


def db_counts() -> dict:
    with SessionLocal() as db:
        return {
            "url_sources": db.scalar(select(func.count()).select_from(models.UrlSource)) or 0,
            "standard_resources": db.scalar(select(func.count()).select_from(models.StandardResource)) or 0,
            "profiled_urls": db.scalar(
                select(func.count()).select_from(models.UrlSource).where(models.UrlSource.governance_status != "pending")
            )
            or 0,
            "governance_runs": db.scalar(select(func.count()).select_from(models.SourceGovernanceRun)) or 0,
            "candidates": db.scalar(select(func.count()).select_from(models.SourceRecordCandidate)) or 0,
            "decisions": db.scalar(select(func.count()).select_from(models.GovernanceDecision)) or 0,
            "ocr_tasks": db.scalar(select(func.count()).select_from(models.OcrDownloadTask)) or 0,
            "file_objects": db.scalar(select(func.count()).select_from(models.FileObject)) or 0,
            "audit_logs": db.scalar(select(func.count()).select_from(models.ProcessAuditLog)) or 0,
        }


def run_samples(base_url: str, limit: int = 1000) -> dict:
    api = f"{base_url.rstrip('/')}/api/v1"
    out: dict[str, dict] = {}
    for sample in SAMPLES:
        status, body = http_json(
            "POST",
            f"{api}/source-governance/run-sample",
            {"sample_type": sample, "limit": limit, "dry_run": True},
        )
        out[sample] = {"status": status, **(body if isinstance(body, dict) else {"raw": body})}
    return out


def profile_urls(base_url: str, limit: int, dry_run: bool) -> dict:
    api = f"{base_url.rstrip('/')}/api/v1"
    before = db_counts()
    status, body = http_json(
        "POST",
        f"{api}/source-governance/profile-url-sources",
        {"limit": limit, "only_ungoverned": True, "dry_run": dry_run},
    )
    after = db_counts()
    return {
        "status": status,
        "body": body,
        "before": before,
        "after": after,
        "delta_profiled": after["profiled_urls"] - before["profiled_urls"],
        "delta_runs": after["governance_runs"] - before["governance_runs"],
        "delta_candidates": after["candidates"] - before["candidates"],
    }


def run_decisions(base_url: str, limit: int, dry_run: bool) -> dict:
    api = f"{base_url.rstrip('/')}/api/v1"
    before = db_counts()["decisions"]
    status, body = http_json(
        "POST",
        f"{api}/governance/run-decisions",
        {"limit": limit, "only_unprocessed": True, "dry_run": dry_run},
    )
    after = db_counts()["decisions"]
    return {"status": status, "body": body, "decisions_before": before, "decisions_after": after}


def create_ocr_tasks(base_url: str, limit: int, dry_run: bool) -> dict:
    api = f"{base_url.rstrip('/')}/api/v1"
    before = db_counts()["ocr_tasks"]
    status, body = http_json(
        "POST",
        f"{api}/ocr-tasks/create-from-decisions",
        {"limit": limit, "only_unprocessed": True, "dry_run": dry_run},
    )
    after = db_counts()["ocr_tasks"]
    return {"status": status, "body": body, "tasks_before": before, "tasks_after": after}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--out", default=str(ROOT / "logs" / "acceptance_metrics.json"))
    args = parser.parse_args()

    metrics = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "schema": schema_check(),
        "counts_before": db_counts(),
        "samples_dry_run_1000": run_samples(args.base_url, 1000),
        "profile_100_dry_run": profile_urls(args.base_url, 100, True),
        "profile_100_write": profile_urls(args.base_url, 100, False),
        "profile_1000_write": profile_urls(args.base_url, 1000, False),
        "decisions_dry_run_500": run_decisions(args.base_url, 500, True),
        "decisions_write_500": run_decisions(args.base_url, 500, False),
        "ocr_create_dry_run_10": create_ocr_tasks(args.base_url, 10, True),
        "ocr_create_write_10": create_ocr_tasks(args.base_url, 10, False),
        "counts_after": db_counts(),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
