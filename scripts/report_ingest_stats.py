from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
LOG_DIR = ROOT / "logs"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text

from app.database import SessionLocal

CHANNEL_SQL = """
SELECT
  CASE
    WHEN us.url LIKE 'https://openstd.samr.gov.cn/bzgk/std/showGb?type=download%' THEN 'openstd_captcha'
    WHEN us.url LIKE 'https://hbba.sacinfo.org.cn/portal/online/%' THEN 'hbba_captcha'
    WHEN us.url LIKE 'https://dbba.sacinfo.org.cn/portal/online/%' THEN 'dbba_captcha'
    WHEN us.url LIKE 'https://%bba.sacinfo.org.cn/portal/download/%' THEN 'sacinfo_token'
    WHEN us.url LIKE 'spc-online-reading://%' THEN 'spc_online'
    WHEN dv.file_path LIKE 'baidupan:%' THEN 'legacy_baidupan'
    ELSE 'local_other'
  END AS channel,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE dv.file_path LIKE 'baidupan:%') AS on_baidu,
  COUNT(*) FILTER (WHERE dv.file_path NOT LIKE 'baidupan:%') AS local_only,
  COUNT(*) FILTER (WHERE dv.downloaded_at >= :since) AS recent
FROM document_versions dv
JOIN url_sources us ON us.id = dv.url_source_id
WHERE dv.is_current = true
GROUP BY 1
ORDER BY total DESC
"""

WORKER_SPECS: tuple[tuple[str, str, str], ...] = (
    ("openstd_captcha_loop", "openstd-file-loop.pid", "openstd-file-loop.out.log"),
    ("sacinfo_captcha_loop", "sacinfo-portal-file-loop.pid", "sacinfo-portal-file-loop.out.log"),
    ("spc_online_loop", "spc-file-loop.pid", "spc-file-loop.out.log"),
)

LOG_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
OPENSTD_OK_RE = re.compile(r'"ok": true.*"status": "archived"')
OPENSTD_FAIL_RE = re.compile(r'"ok": false')
SACINFO_OK_RE = re.compile(r'sacinfo_batch_result .*"ok": true.*"status": "archived"')
SACINFO_FAIL_RE = re.compile(r'sacinfo_batch_result .*"ok": false')
SPC_OK_RE = re.compile(r'spc_batch_result .*"ok": true')
SPC_FAIL_RE = re.compile(r'spc_batch_result .*"ok": false')


def _parse_log_ts(line: str) -> datetime | None:
    match = LOG_TS_RE.match(line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _count_log_events(path: Path, since: datetime, ok_pattern: re.Pattern[str], fail_pattern: re.Pattern[str]) -> dict[str, int]:
    if not path.exists():
        return {"ok": 0, "fail": 0, "lines_scanned": 0}
    ok = fail = scanned = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ts = _parse_log_ts(line)
        if ts is not None:
            if ts < since:
                continue
            scanned += 1
            if ok_pattern.search(line):
                ok += 1
            elif fail_pattern.search(line):
                fail += 1
            continue
        if ts is None and path.stat().st_mtime > since.timestamp():
            if line.startswith("openstd_batch_result ") or line.startswith("sacinfo_batch_result ") or line.startswith("spc_batch_result "):
                scanned += 1
                if ok_pattern.search(line):
                    ok += 1
                elif fail_pattern.search(line):
                    fail += 1
    return {"ok": ok, "fail": fail, "lines_scanned": scanned}


def _worker_status(name: str, pid_file: str, log_file: str) -> dict:
    pid_path = LOG_DIR / pid_file
    log_path = LOG_DIR / log_file
    pid: int | None = None
    alive = False
    if pid_path.exists():
        raw = pid_path.read_text(encoding="utf-8", errors="replace").strip()
        if raw.isdigit():
            pid = int(raw)
            try:
                import os

                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
    log_mtime: str | None = None
    if log_path.exists():
        log_mtime = datetime.fromtimestamp(log_path.stat().st_mtime, UTC).isoformat()
    return {
        "name": name,
        "pid": pid,
        "alive": alive,
        "pid_file": str(pid_path),
        "log_file": str(log_path),
        "log_mtime_utc": log_mtime,
    }


def collect_report(*, interval_minutes: int) -> dict:
    since = datetime.now(UTC) - timedelta(minutes=interval_minutes)
    with SessionLocal() as db:
        storage_backend = db.execute(text("SELECT value FROM system_settings WHERE key = 'storage_backend'")).scalar()
        channels = [
            {
                "channel": row[0],
                "total": row[1],
                "on_baidu": row[2],
                "local_only": row[3],
                f"last_{interval_minutes}m": row[4],
            }
            for row in db.execute(text(CHANNEL_SQL), {"since": since}).all()
        ]
        totals = db.execute(
            text(
                """
                SELECT
                  COUNT(*) AS current_versions,
                  COUNT(*) FILTER (WHERE file_path LIKE 'baidupan:%') AS on_baidu,
                  COUNT(*) FILTER (WHERE file_path NOT LIKE 'baidupan:%') AS local_only,
                  COUNT(*) FILTER (WHERE downloaded_at >= :since) AS recent
                FROM document_versions
                WHERE is_current = true
                """
            ),
            {"since": since},
        ).one()

        sync_status = db.execute(
            text(
                """
                SELECT COALESCE(sr.sync_status, '(null)'), COUNT(*)
                FROM standard_resources sr
                GROUP BY 1
                ORDER BY COUNT(*) DESC
                LIMIT 12
                """
            )
        ).all()

        ingest_failures = db.execute(
            text(
                """
                SELECT ts.adapter_key, COALESCE(sr.sync_status, '(null)'), COUNT(*)
                FROM standard_resources sr
                JOIN trusted_sources ts ON ts.id = sr.source_id
                WHERE sr.sync_status IN ('文件采集失败', '文件不可下载')
                GROUP BY 1, 2
                ORDER BY COUNT(*) DESC
                LIMIT 20
                """
            )
        ).all()

    workers = [_worker_status(*spec) for spec in WORKER_SPECS]
    log_activity = {
        "openstd_captcha_loop": _count_log_events(
            LOG_DIR / "openstd-file-loop.out.log", since, OPENSTD_OK_RE, OPENSTD_FAIL_RE
        ),
        "sacinfo_captcha_loop": _count_log_events(
            LOG_DIR / "sacinfo-portal-file-loop.out.log", since, SACINFO_OK_RE, SACINFO_FAIL_RE
        ),
        "spc_online_loop": _count_log_events(LOG_DIR / "spc-file-loop.out.log", since, SPC_OK_RE, SPC_FAIL_RE),
    }

    channel_map = {item["channel"]: item for item in channels}
    return {
        "reported_at": datetime.now(UTC).isoformat(),
        "interval_minutes": interval_minutes,
        "storage_backend": storage_backend,
        "summary": {
            "current_versions_total": totals[0],
            "on_baidu_total": totals[1],
            "local_only_total": totals[2],
            f"ingested_last_{interval_minutes}m_total": totals[3],
            "openstd_captcha_total": channel_map.get("openstd_captcha", {}).get("total", 0),
            "hbba_captcha_total": channel_map.get("hbba_captcha", {}).get("total", 0),
            "dbba_captcha_total": channel_map.get("dbba_captcha", {}).get("total", 0),
            "spc_online_total": channel_map.get("spc_online", {}).get("total", 0),
            f"openstd_last_{interval_minutes}m": channel_map.get("openstd_captcha", {}).get(f"last_{interval_minutes}m", 0),
            f"hbba_last_{interval_minutes}m": channel_map.get("hbba_captcha", {}).get(f"last_{interval_minutes}m", 0),
            f"dbba_last_{interval_minutes}m": channel_map.get("dbba_captcha", {}).get(f"last_{interval_minutes}m", 0),
            f"spc_last_{interval_minutes}m": channel_map.get("spc_online", {}).get(f"last_{interval_minutes}m", 0),
        },
        "channels": channels,
        "workers": workers,
        "log_activity_last_interval": log_activity,
        "sync_status_top": {f"{status}": count for status, count in sync_status},
        "ingest_failure_by_source": [
            {"adapter_key": row[0], "sync_status": row[1], "count": row[2]} for row in ingest_failures
        ],
    }


def format_text(report: dict) -> str:
    interval = report["interval_minutes"]
    s = report["summary"]
    lines = [
        f"[{report['reported_at']}] ingest monitor ({interval}m)",
        f"storage={report['storage_backend']} | versions={s['current_versions_total']} baidu={s['on_baidu_total']} local_only={s['local_only_total']} | +{s[f'ingested_last_{interval}m_total']} in last {interval}m",
        (
            "channels: "
            f"openstd={s['openstd_captcha_total']} (+{s[f'openstd_last_{interval}m']}) | "
            f"hbba={s['hbba_captcha_total']} (+{s[f'hbba_last_{interval}m']}) | "
            f"dbba={s['dbba_captcha_total']} (+{s[f'dbba_last_{interval}m']}) | "
            f"spc={s['spc_online_total']} (+{s[f'spc_last_{interval}m']})"
        ),
    ]
    for worker in report["workers"]:
        state = "running" if worker["alive"] else "stopped"
        lines.append(f"worker {worker['name']}: {state} pid={worker['pid']}")
    for name, activity in report["log_activity_last_interval"].items():
        lines.append(f"log {name}: ok={activity['ok']} fail={activity['fail']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report standard document ingest statistics.")
    parser.add_argument("--interval-minutes", type=int, default=30)
    parser.add_argument("--format", choices=("json", "text", "both"), default="both")
    parser.add_argument("--append-log", type=Path, help="Append text summary to this log file")
    parser.add_argument("--append-jsonl", type=Path, help="Append JSON report as one line to this file")
    args = parser.parse_args()

    report = collect_report(interval_minutes=max(args.interval_minutes, 1))
    text_output = format_text(report)

    if args.format in {"text", "both"}:
        print(text_output)
    if args.format in {"json", "both"}:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.append_log:
        args.append_log.parent.mkdir(parents=True, exist_ok=True)
        with args.append_log.open("a", encoding="utf-8") as handle:
            handle.write(text_output + "\n\n")
    if args.append_jsonl:
        args.append_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.append_jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
