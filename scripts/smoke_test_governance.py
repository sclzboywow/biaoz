#!/usr/bin/env python3
"""Governance HTTP smoke test for acceptance.

Usage:
  python scripts/smoke_test_governance.py
  python scripts/smoke_test_governance.py --base-url http://127.0.0.1:8000 --dry-run true
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SAMPLE_TYPES = ("official_domains", "pdf_links", "cloud_drive", "commercial_sites")


@dataclass
class CheckResult:
    name: str
    url: str
    method: str
    status: int | None = None
    ok: bool = False
    keys: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    warning: str | None = None


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _http_call(method: str, url: str, payload: dict | None = None, timeout: int = 180) -> tuple[int, dict | list | str]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        if not raw:
            return resp.status, {}
        try:
            return resp.status, json.loads(raw)
        except json.JSONDecodeError:
            return resp.status, raw


def _pick_keys(data: Any, keys: list[str]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"raw": data}
    return {k: data.get(k) for k in keys if k in data}


def _run_check(
    results: list[CheckResult],
    *,
    name: str,
    method: str,
    url: str,
    payload: dict | None = None,
    key_fields: list[str] | None = None,
    allow_empty: bool = False,
) -> None:
    item = CheckResult(name=name, url=url, method=method)
    try:
        status, body = _http_call(method, url, payload)
        item.status = status
        if status >= 500:
            item.error = json.dumps(body, ensure_ascii=False)[:2000] if isinstance(body, (dict, list)) else str(body)[:2000]
        elif status >= 400:
            item.error = f"HTTP {status}: {body!r}"[:2000]
        else:
            item.ok = True
            item.keys = _pick_keys(body, key_fields or [])
            if allow_empty and isinstance(body, dict):
                zero_fields = [k for k, v in item.keys.items() if v in (0, None, [], {})]
                if zero_fields and len(zero_fields) == len(item.keys):
                    item.warning = f"empty metrics: {', '.join(zero_fields)}"
    except urllib.error.HTTPError as exc:
        item.status = exc.code
        body = exc.read().decode("utf-8", errors="replace")
        item.error = body[:2000]
        if exc.code >= 500:
            item.error = f"HTTP {exc.code}: {body[:2000]}"
    except Exception as exc:
        item.error = str(exc)
    results.append(item)
    status_text = item.status if item.status is not None else "-"
    flag = "PASS" if item.ok else "FAIL"
    print(f"[{flag}] {method} {url} -> {status_text}")
    if item.keys:
        print(f"       keys: {json.dumps(item.keys, ensure_ascii=False)}")
    if item.warning:
        print(f"       warn: {item.warning}")
    if item.error:
        print(f"       error: {item.error[:500]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Governance acceptance smoke test")
    parser.add_argument("--base-url", default=os.getenv("API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--profile-limit", type=int, default=100)
    parser.add_argument("--decision-limit", type=int, default=100)
    parser.add_argument("--dry-run", default="true", help="true/false for POST dry_run payloads")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    api = f"{base}/api/v1"
    dry_run = _parse_bool(args.dry_run)
    results: list[CheckResult] = []

    print(f"== smoke test base={base} dry_run={dry_run} ==")

    _run_check(
        results,
        name="health",
        method="GET",
        url=f"{base}/health",
        key_fields=["status", "system"],
    )
    _run_check(
        results,
        name="governance-dashboard-summary",
        method="GET",
        url=f"{api}/dashboard/governance-summary",
        key_fields=["url_total", "profiled_url_count", "ungoverned_url_count", "need_ocr_count"],
        allow_empty=True,
    )
    _run_check(
        results,
        name="governance-summary",
        method="GET",
        url=f"{api}/governance/summary",
        key_fields=["url_total", "profiled_url_count"],
        allow_empty=True,
    )
    _run_check(
        results,
        name="ocr-tasks-summary",
        method="GET",
        url=f"{api}/ocr-tasks/summary",
        key_fields=["pending_ocr", "archived", "total"],
        allow_empty=True,
    )
    _run_check(
        results,
        name="file-objects-summary",
        method="GET",
        url=f"{api}/file-objects/summary",
        key_fields=["total", "valid_pdf_count"],
        allow_empty=True,
    )
    _run_check(
        results,
        name="profile-url-sources",
        method="POST",
        url=f"{api}/source-governance/profile-url-sources",
        payload={"limit": args.profile_limit, "only_ungoverned": True, "dry_run": dry_run},
        key_fields=["total", "profiled", "run_id"],
        allow_empty=True,
    )

    for sample in SAMPLE_TYPES:
        _run_check(
            results,
            name=f"run-sample-{sample}",
            method="POST",
            url=f"{api}/source-governance/run-sample",
            payload={"sample_type": sample, "limit": 100, "dry_run": True},
            key_fields=[
                "sample_type",
                "scanned",
                "total",
                "profiled",
                "high_priority_count",
                "clue_only_count",
                "blacklist_candidate_count",
            ],
            allow_empty=True,
        )

    _run_check(
        results,
        name="run-decisions",
        method="POST",
        url=f"{api}/governance/run-decisions",
        payload={"limit": args.decision_limit, "only_unprocessed": True, "dry_run": True},
        key_fields=["processed", "auto_confirmed", "need_review", "dry_run"],
        allow_empty=True,
    )
    _run_check(
        results,
        name="create-ocr-from-decisions",
        method="POST",
        url=f"{api}/ocr-tasks/create-from-decisions",
        payload={"limit": 10, "only_unprocessed": True, "dry_run": True},
        key_fields=["created", "skipped", "scanned"],
        allow_empty=True,
    )

    passed = sum(1 for r in results if r.ok)
    failed = sum(1 for r in results if not r.ok)
    warnings = [r.name for r in results if r.warning]

    summary = {
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "total": len(results),
        "dry_run": dry_run,
        "results": [
            {
                "name": r.name,
                "url": r.url,
                "method": r.method,
                "status": r.status,
                "ok": r.ok,
                "keys": r.keys,
                "warning": r.warning,
                "error": r.error,
            }
            for r in results
        ],
    }
    print("\n== Summary ==")
    print(json.dumps({"passed": passed, "failed": failed, "warnings": warnings}, ensure_ascii=False, indent=2))
    out = Path(__file__).resolve().parents[1] / "logs" / "smoke_test_governance.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
