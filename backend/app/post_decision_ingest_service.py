"""决策通过后按通道触发文件采集。"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.batch2_admission import BATCH2_STANDARD_BODY_ADAPTER_KEYS
from app.governance_decision_engine import DECISION_AUTO_CONFIRMED, DECISION_AUTO_MERGED
from app.settings_store import get_bool_setting, get_int_setting

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
PYTHON = REPO_ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

INGESTIBLE_DECISIONS = frozenset({DECISION_AUTO_CONFIRMED, DECISION_AUTO_MERGED})

ADAPTER_TO_CHANNEL: dict[str, str] = {
    "samr_gb_all_public": "openstd",
    "samr_std_public": "openstd",
    "samr_industry_standard_public": "sacinfo_industry",
    "samr_local_standard_public": "sacinfo_local",
    "samr_enterprise_standard_public": "qybz",
    "spc_standard_online": "spc_online",
    **{adapter_key: "batch2_standard_body" for adapter_key in BATCH2_STANDARD_BODY_ADAPTER_KEYS},
}

CHANNEL_SCRIPTS: dict[str, tuple[str, list[str]]] = {
    "openstd": ("batch_ingest_openstd_gb688_files.py", []),
    "sacinfo_industry": ("batch_ingest_sacinfo_portal_files.py", ["--platform", "industry"]),
    "sacinfo_local": ("batch_ingest_sacinfo_portal_files.py", ["--platform", "local"]),
    "qybz": ("batch_ingest_qybz_files.py", []),
    "spc_online": ("batch_ingest_spc_online_files.py", []),
    "batch2_standard_body": ("batch_ingest_batch2_files.py", []),
}


def _channel_for_resource(resource: models.StandardResource, trusted_source: models.TrustedSource | None) -> str | None:
    adapter_key = (trusted_source.adapter_key if trusted_source else "") or ""
    return ADAPTER_TO_CHANNEL.get(adapter_key)


def group_resources_by_channel(
    db: Session,
    resource_ids: list[int],
) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    if not resource_ids:
        return grouped
    rows = list(
        db.scalars(
            select(models.StandardResource)
            .where(models.StandardResource.id.in_(resource_ids))
            .order_by(models.StandardResource.id.asc())
        ).all()
    )
    source_cache: dict[int, models.TrustedSource | None] = {}
    for resource in rows:
        if resource.source_id not in source_cache:
            source_cache[resource.source_id] = db.get(models.TrustedSource, resource.source_id)
        trusted_source = source_cache[resource.source_id]
        channel = _channel_for_resource(resource, trusted_source)
        if channel:
            grouped[channel].append(resource.id)
    return dict(grouped)


def _run_channel_batch(
    channel: str,
    resource_ids: list[int],
    *,
    defer_baidu_upload: bool = True,
) -> dict:
    if not resource_ids:
        return {"channel": channel, "skipped": True, "reason": "empty"}
    script_name, extra_args = CHANNEL_SCRIPTS[channel]
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        return {"channel": channel, "skipped": True, "reason": f"missing_script:{script_name}"}

    id_csv = ",".join(str(item) for item in resource_ids)
    cmd = [
        str(PYTHON),
        str(script_path),
        "--only-resource-ids",
        id_csv,
        "--limit",
        str(len(resource_ids)),
    ]
    if defer_baidu_upload:
        cmd.append("--defer-baidu-upload")
    cmd.extend(extra_args)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    completed = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT / "backend"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=max(600, len(resource_ids) * 120),
    )
    return {
        "channel": channel,
        "resource_ids": resource_ids,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout.splitlines()[-6:],
        "stderr_tail": completed.stderr.splitlines()[-3:],
    }


def trigger_post_decision_ingest(
    db: Session,
    *,
    resource_ids: list[int],
    limit: int | None = None,
) -> dict:
    """对 AUTO_CONFIRMED / AUTO_MERGED 资源按通道触发一次文件采集。"""
    if not get_bool_setting(db, "ingest_enabled", default=False):
        return {"enabled": False, "skipped": True, "reason": "ingest_disabled"}
    if not get_bool_setting(db, "post_decision_ingest_enabled", default=True):
        return {"enabled": False, "skipped": True, "reason": "post_decision_ingest_disabled"}

    max_items = limit if limit is not None else get_int_setting(db, "post_decision_ingest_limit", 50)
    max_items = max(1, min(max_items, 200))
    trimmed_ids = resource_ids[:max_items]
    grouped = group_resources_by_channel(db, trimmed_ids)
    if not get_bool_setting(db, "batch2_file_ingest_enabled", default=False):
        grouped = {channel: ids for channel, ids in grouped.items() if channel != "batch2_standard_body"}

    channel_results: list[dict] = []
    for channel, ids in grouped.items():
        channel_results.append(_run_channel_batch(channel, ids))

    return {
        "enabled": True,
        "requested": len(resource_ids),
        "processed": len(trimmed_ids),
        "channels": {key: len(value) for key, value in grouped.items()},
        "results": channel_results,
    }


def collect_ingestible_resource_ids(
    db: Session,
    *,
    decision_stats: dict,
    run_id: int | None,
) -> list[int]:
    """从本轮决策结果中收集可触发采集的资源 ID。"""
    if run_id is None:
        return []
    rows = list(
        db.scalars(
            select(models.GovernanceDecision.target_id)
            .where(models.GovernanceDecision.run_id == run_id)
            .where(models.GovernanceDecision.decision.in_(tuple(INGESTIBLE_DECISIONS)))
            .order_by(models.GovernanceDecision.id.asc())
        ).all()
    )
    if rows:
        return rows
    confirmed = int(decision_stats.get("auto_confirmed") or 0)
    merged = int(decision_stats.get("auto_merged") or 0)
    if confirmed + merged <= 0:
        return []
    return []
