from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


CHANNEL_SQL = """
SELECT
  CASE
    WHEN us.url LIKE 'https://openstd.samr.gov.cn/bzgk/std/showGb?type=download%' THEN 'openstd'
    WHEN us.url LIKE 'https://hbba.sacinfo.org.cn/portal/online/%' THEN 'sacinfo_industry'
    WHEN us.url LIKE 'https://dbba.sacinfo.org.cn/portal/online/%' THEN 'sacinfo_local'
    WHEN us.url LIKE 'https://www.ttbz.org.cn/standardDetail/%' THEN 'ttbz'
    WHEN us.url LIKE 'https://www.qybz.org.cn/user/detail/%' THEN 'qybz'
    WHEN us.url LIKE 'spc-online-reading://%' THEN 'spc_online'
    WHEN dv.file_path LIKE 'baidupan:%' THEN 'legacy_baidupan'
    ELSE 'other'
  END AS channel,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE dv.downloaded_at >= :since) AS recent,
  COUNT(*) FILTER (
    WHERE dv.file_path LIKE 'baidupan:%'
       OR dv.remark LIKE '%remote_uri%baidupan:%'
  ) AS on_baidu,
  MAX(dv.downloaded_at) AS latest
FROM document_versions dv
JOIN url_sources us ON us.id = dv.url_source_id
WHERE dv.is_current = true
GROUP BY 1
ORDER BY total DESC
"""


WORKER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "openstd",
        "name": "OpenSTD 国标下载",
        "group": "文件采集",
        "pid_file": "openstd-file-loop.pid",
        "log_file": "openstd-file-loop.out.log",
        "cursor_files": ["openstd-file-loop.cursor"],
        "summary_prefixes": ["openstd_batch_summary"],
        "upload_prefixes": ["openstd_baidu_upload_summary"],
        "stale_minutes": 8,
        "channel": "openstd",
    },
    {
        "key": "sacinfo_industry",
        "name": "行业标准下载",
        "group": "文件采集",
        "pid_file": "sacinfo-portal-industry-file-loop.pid",
        "log_file": "sacinfo-portal-industry-file-loop.out.log",
        "cursor_files": ["sacinfo-portal-loop-industry.cursor"],
        "summary_prefixes": ["sacinfo_batch_summary"],
        "upload_prefixes": ["sacinfo_baidu_upload_summary"],
        "stale_minutes": 8,
        "channel": "sacinfo_industry",
    },
    {
        "key": "sacinfo_local",
        "name": "地方标准下载",
        "group": "文件采集",
        "pid_file": "sacinfo-portal-local-file-loop.pid",
        "log_file": "sacinfo-portal-local-file-loop.out.log",
        "cursor_files": ["sacinfo-portal-loop-local.cursor"],
        "summary_prefixes": ["sacinfo_batch_summary"],
        "upload_prefixes": ["sacinfo_baidu_upload_summary"],
        "stale_minutes": 8,
        "channel": "sacinfo_local",
    },
    {
        "key": "spc_online",
        "name": "SPC 在线阅读下载",
        "group": "文件采集",
        "pid_file": "spc-file-loop.pid",
        "log_file": "spc-file-loop.out.log",
        "cursor_files": ["spc-file-loop-CN.cursor"],
        "summary_prefixes": ["spc_batch_summary"],
        "upload_prefixes": ["spc_baidu_upload_summary"],
        "stale_minutes": 8,
        "channel": "spc_online",
    },
    {
        "key": "qybz",
        "name": "企业标准下载",
        "group": "文件采集",
        "pid_file": "qybz-file-loop.pid",
        "log_file": "qybz-file-loop.out.log",
        "summary_prefixes": ["qybz_batch_summary"],
        "upload_prefixes": ["qybz_baidu_upload_summary"],
        "stale_minutes": 8,
        "channel": "qybz",
    },
    {
        "key": "ttbz",
        "name": "团体标准下载",
        "group": "文件采集",
        "pid_file": "ttbz-file-loop.pid",
        "log_file": "ttbz-file-loop.out.log",
        "summary_prefixes": ["ttbz_batch_summary"],
        "upload_prefixes": ["ttbz_baidu_upload_summary"],
        "stale_minutes": 8,
        "channel": "ttbz",
    },
    {
        "key": "spc_metadata",
        "name": "SPC 元数据分片同步",
        "group": "元数据同步",
        "pid_file": "spc-metadata-slices-loop.pid",
        "log_file": "spc-metadata-slices-loop.out.log",
        "summary_prefixes": ["spc_slice_result"],
        "stale_minutes": 25,
    },
    {
        "key": "trusted_sources",
        "name": "可信源元数据同步",
        "group": "元数据同步",
        "pid_file": "trusted-sources-loop.pid",
        "log_file": "trusted-sources-loop.out.log",
        "summary_prefixes": ["sync_result"],
        "stale_minutes": 25,
    },
    {
        "key": "samr_sync_worker",
        "name": "SAMR 同步 Worker",
        "group": "元数据同步",
        "pid_file": "samr-sync-worker.pid",
        "log_file": "samr-sync-worker.log",
        "stale_minutes": 25,
    },
    {
        "key": "ocr_worker",
        "name": "OCR 受控下载 Worker",
        "group": "治理自动化",
        "pid_file": "ocr-worker.pid",
        "log_file": "ocr-worker.out.log",
        "stale_minutes": 15,
        "db_activity": "ocr_download_tasks",
    },
    {
        "key": "governance_loop",
        "name": "治理自动化循环",
        "group": "治理自动化",
        "pid_file": "governance-loop.pid",
        "log_file": "governance-loop.out.log",
        "cursor_files": ["governance-loop.url-profile.cursor"],
        "summary_prefixes": [
            "governance_pipeline_state",
            "governance_profile_summary",
            "governance_profile_skipped",
            "governance_decisions_summary",
            "governance_ocr_tasks_summary",
            "governance_alert_sweep_summary",
            "governance_batch_summary",
        ],
        "stale_minutes": 25,
    },
    {
        "key": "baidu_pan_sync",
        "name": "百度网盘同步",
        "group": "存储同步",
        "pid_file": "baidu-pan-sync-loop.pid",
        "log_file": "baidu-pan-sync-loop.out.log",
        "summary_prefixes": ["baidu_pan_sync_summary"],
        "stale_minutes": 12,
    },
    {
        "key": "ingest_monitor",
        "name": "采集监控与拉起",
        "group": "监控",
        "pid_file": "ingest-monitor.pid",
        "log_file": "ingest-monitor.runtime.log",
        "stale_minutes": 40,
    },
)


JSON_LINE_RE = re.compile(r"(?P<prefix>[A-Za-z0-9_]+)\s+(?P<payload>\{.*\})")
EXIT_RE = re.compile(r"\bexit=(?P<exit_code>\d+)")
START_RE = re.compile(r"\b(start|begin)\b", re.IGNORECASE)
FINISH_RE = re.compile(r"\b(finish|end)\b", re.IGNORECASE)


def _log_root() -> Path:
    configured = os.getenv("INGEST_LOG_ROOT")
    if configured:
        return Path(configured)
    cwd_logs = Path.cwd() / "logs"
    if cwd_logs.exists():
        return cwd_logs
    return Path.cwd().parent / "logs"


def _read_text(path: Path, max_chars: int = 200_000) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    if len(data) > max_chars:
        data = data[-max_chars:]
    return data.decode("utf-8-sig", errors="replace")


def _read_pid(path: Path) -> int | None:
    raw = _read_text(path, 100).strip()
    return int(raw) if raw.isdigit() else None


def _process_alive(pid: int | None) -> bool | None:
    if not pid:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return None
    # Host PowerShell PIDs are not visible from Linux Docker containers.
    if Path("/.dockerenv").exists():
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _parse_json_line(line: str) -> tuple[str, dict[str, Any]] | None:
    match = JSON_LINE_RE.search(line)
    if not match:
        return None
    try:
        return match.group("prefix"), json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return None


def _cursor_value(log_root: Path, spec: dict[str, Any]) -> str | None:
    for file_name in spec.get("cursor_files", []):
        path = log_root / file_name
        value = _read_text(path, 100).strip()
        if value:
            return value
    return None


def _last_matching_payload(lines: list[str], prefixes: list[str]) -> dict[str, Any] | None:
    wanted = set(prefixes)
    for line in reversed(lines):
        parsed = _parse_json_line(line)
        if parsed and parsed[0] in wanted:
            return parsed[1]
    return None


def _ocr_download_task_activity(db: Session, minutes: int) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    row = db.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (WHERE status = 'RUNNING') AS running,
              COUNT(*) FILTER (WHERE status = 'ARCHIVED' AND finished_at >= :since) AS archived,
              COUNT(*) FILTER (WHERE status = 'DUPLICATE_FILE' AND finished_at >= :since) AS duplicate,
              COUNT(*) FILTER (
                WHERE status IN ('OCR_FAILED', 'CAPTCHA_FAILED', 'DOWNLOAD_FAILED', 'PDF_INVALID')
                  AND finished_at >= :since
              ) AS failed,
              COUNT(*) FILTER (WHERE started_at >= :since) AS started,
              COUNT(*) FILTER (WHERE status = 'PENDING') AS pending,
              MAX(COALESCE(finished_at, started_at)) AS latest
            FROM ocr_download_tasks
            """
        ),
        {"since": since},
    ).mappings().one()
    return dict(row)


def _worker_db_activity(db: Session | None, spec: dict[str, Any]) -> dict[str, Any] | None:
    if db is None:
        return None
    activity_key = spec.get("db_activity")
    if activity_key == "ocr_download_tasks":
        minutes = int(spec.get("stale_minutes", 15))
        activity = _ocr_download_task_activity(db, minutes)
        activity["summary"] = {
            "ok": int(activity.get("archived") or 0) + int(activity.get("duplicate") or 0),
            "errors": int(activity.get("failed") or 0),
            "total": int(activity.get("started") or 0),
            "pending": int(activity.get("pending") or 0),
        }
        return activity
    return None


def _last_line_index(lines: list[str], needle: str) -> int:
    for index in range(len(lines) - 1, -1, -1):
        if needle in lines[index]:
            return index
    return -1


def _openstd_idle_status(lines: list[str], last_exit: int | None) -> tuple[str, str] | None:
    empty_idx = _last_line_index(lines, "openstd_batch_candidates []")
    if empty_idx < 0:
        return None
    summary_idx = -1
    for index in range(len(lines) - 1, -1, -1):
        parsed = _parse_json_line(lines[index])
        if parsed and parsed[0] == "openstd_batch_summary":
            summary_idx = index
            break
    if empty_idx > summary_idx and last_exit in (None, 0):
        return "running", "当前无待下载候选，OpenSTD 循环空闲运行中"
    return None


def _status_from_db_activity(spec: dict[str, Any], activity: dict[str, Any]) -> tuple[str, str] | None:
    running = int(activity.get("running") or 0)
    archived = int(activity.get("archived") or 0)
    duplicate = int(activity.get("duplicate") or 0)
    failed = int(activity.get("failed") or 0)
    pending = int(activity.get("pending") or 0)
    started = int(activity.get("started") or 0)
    stale_minutes = spec.get("stale_minutes", 10)
    active_recent = running > 0 or started > 0 or archived + duplicate > 0

    latest = activity.get("latest")
    if isinstance(latest, datetime) and latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    stale_after = timedelta(minutes=stale_minutes)
    latest_fresh = isinstance(latest, datetime) and latest >= datetime.now(UTC) - stale_after

    if not active_recent and not latest_fresh:
        return None

    if failed > 0 and archived + duplicate == 0 and running == 0 and started == 0:
        return "warning", f"近 {stale_minutes} 分钟 OCR 失败 {failed} 条，待处理 {pending} 条"
    return (
        "running",
        f"任务队列活跃：运行 {running}，近 {stale_minutes} 分钟启动 {started}，归档 {archived + duplicate}，失败 {failed}，待 OCR {pending}",
    )


def _status_from(
    spec: dict[str, Any],
    pid: int | None,
    pid_alive: bool | None,
    log_path: Path,
    lines: list[str],
    channel_activity: dict[str, Any] | None,
    db_activity: dict[str, Any] | None = None,
) -> tuple[str, str]:
    db_status = _status_from_db_activity(spec, db_activity) if db_activity else None
    if db_status:
        return db_status

    if not pid and not log_path.exists():
        if db_activity and int(db_activity.get("pending") or 0) > 0:
            return "warning", f"无宿主机日志，但 OCR 队列仍有 {int(db_activity['pending'])} 条待处理"
        return "stopped", "没有 PID 和日志"
    mtime = datetime.fromtimestamp(log_path.stat().st_mtime, UTC) if log_path.exists() else None
    fresh = bool(mtime and mtime >= datetime.now(UTC) - timedelta(minutes=spec.get("stale_minutes", 10)))
    last_exit = None
    for line in reversed(lines):
        match = EXIT_RE.search(line)
        if match:
            last_exit = int(match.group("exit_code"))
            break
    summary = _last_matching_payload(lines, spec.get("summary_prefixes", [])) or {}
    errors = int(summary.get("errors") or summary.get("failed") or 0)
    if spec.get("key") == "openstd":
        idle_status = _openstd_idle_status(lines, last_exit)
        if idle_status:
            return idle_status
    if fresh and (last_exit not in (None, 0) or errors > 0):
        return "warning", f"最近批次有失败：exit={last_exit}, errors={errors}"
    if fresh:
        return "running", "日志仍在更新"
    if channel_activity and channel_activity.get("latest"):
        latest = channel_activity["latest"]
        if isinstance(latest, datetime):
            stale_after = timedelta(minutes=spec.get("stale_minutes", 10))
            if latest >= datetime.now(UTC) - stale_after:
                return "running", f"数据库仍有写入：最近 {latest.isoformat()}"
    if pid and pid_alive is True:
        return "stale", "进程存在但日志超时"
    if pid and pid_alive is None:
        return "stale", "容器内无法确认宿主机 PID，日志已超时"
    return "stopped", "进程未运行或 PID 已失效"


def _worker_summary(
    log_root: Path,
    spec: dict[str, Any],
    channel_activity_map: dict[str, dict[str, Any]],
    *,
    db: Session | None = None,
) -> dict[str, Any]:
    pid_path = log_root / spec["pid_file"]
    log_path = log_root / spec["log_file"]
    pid = _read_pid(pid_path)
    pid_alive = _process_alive(pid)
    lines = _read_text(log_path).splitlines()
    tail = lines[-8:]
    channel_activity = channel_activity_map.get(spec.get("channel", ""))
    db_activity = _worker_db_activity(db, spec)
    status, status_message = _status_from(spec, pid, pid_alive, log_path, lines, channel_activity, db_activity)
    summary = _last_matching_payload(lines, spec.get("summary_prefixes", []))
    upload_summary = _last_matching_payload(lines, spec.get("upload_prefixes", []))
    if db_activity and db_activity.get("summary"):
        summary = {**(summary or {}), **db_activity["summary"]}
    last_exit = None
    last_started = None
    last_finished = None
    for line in reversed(lines):
        if last_exit is None:
            match = EXIT_RE.search(line)
            if match:
                last_exit = int(match.group("exit_code"))
        if last_started is None and START_RE.search(line):
            last_started = line[:240]
        if last_finished is None and FINISH_RE.search(line):
            last_finished = line[:240]
        if last_exit is not None and last_started and last_finished:
            break
    log_mtime = datetime.fromtimestamp(log_path.stat().st_mtime, UTC).isoformat() if log_path.exists() else None
    return {
        "key": spec["key"],
        "name": spec["name"],
        "group": spec["group"],
        "status": status,
        "status_message": status_message,
        "pid": pid,
        "pid_alive": pid_alive,
        "cursor": _cursor_value(log_root, spec),
        "last_exit": last_exit,
        "last_started": last_started,
        "last_finished": last_finished,
        "log_mtime": log_mtime,
        "log_file": str(log_path),
        "pid_file": str(pid_path),
        "summary": summary,
        "upload_summary": upload_summary,
        "channel_activity": channel_activity,
        "db_activity": db_activity,
        "tail": tail,
    }


def _database_summary(db: Session, interval_minutes: int) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(minutes=interval_minutes)
    channels = [
        {"channel": row[0], "total": row[1], "recent": row[2], "on_baidu": row[3], "latest": row[4]}
        for row in db.execute(text(CHANNEL_SQL), {"since": since}).all()
    ]
    totals = db.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*) FROM standard_resources) AS standard_resources,
              (SELECT COUNT(*) FROM url_sources) AS url_sources,
              (SELECT COUNT(*) FROM documents) AS documents,
              (SELECT COUNT(*) FROM document_versions) AS document_versions,
              (SELECT COUNT(*) FROM document_versions WHERE downloaded_at >= :since) AS recent_versions,
              (SELECT COUNT(*) FROM check_logs WHERE checked_at >= :since) AS recent_checks
            """
        ),
        {"since": since},
    ).mappings().one()
    return {"totals": dict(totals), "channels": channels}


def ingest_runtime_summary(db: Session, interval_minutes: int = 30) -> dict[str, Any]:
    log_root = _log_root()
    database = _database_summary(db, interval_minutes)
    channel_activity_map = {item["channel"]: item for item in database["channels"]}
    workers = [_worker_summary(log_root, spec, channel_activity_map, db=db) for spec in WORKER_SPECS]
    status_counts: dict[str, int] = {}
    for worker in workers:
        status_counts[worker["status"]] = status_counts.get(worker["status"], 0) + 1
    return {
        "reported_at": datetime.now(UTC).isoformat(),
        "interval_minutes": interval_minutes,
        "log_root": str(log_root),
        "status_counts": status_counts,
        "database": database,
        "workers": workers,
    }
