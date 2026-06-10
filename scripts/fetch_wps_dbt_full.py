"""
全量拉取 WPS 多维表「标准查询系统」到本地 SQLite，供后续数据治理。

依赖：多维表 AirScript 已升级为 scripts/wps_dbt_airscript.js (v2.1)，
      read 须返回 offset 并支持 Context.argv.offset 分页。

用法:
  backend/.venv/Scripts/python.exe scripts/fetch_wps_dbt_full.py
  backend/.venv/Scripts/python.exe scripts/fetch_wps_dbt_full.py --resume
  backend/.venv/Scripts/python.exe scripts/fetch_wps_dbt_full.py --dry-run

环境变量（可选）:
  WPS_DBT_WEBHOOK_URL
  WPS_AIRSCRIPT_TOKEN
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "wps_standard_query_raw.db"
STATE_PATH = DATA_DIR / "wps_dbt_fetch_state.json"
LOG_PATH = ROOT / "logs" / "wps-dbt-fetch.log"

DEFAULT_WEBHOOK_URL = (
    "https://365.kdocs.cn/api/v3/ide/file/296498309264/script/V2-V8JCUpZX1qTQRg5B39Jec/sync_task"
)
DEFAULT_TOKEN = ""
PAGE_SIZE = 1000
EXPECTED_TOTAL = 623_166
REQUEST_INTERVAL_SEC = 0.35
MAX_RETRIES = 5

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wps_standard_query_raw (
    record_id     TEXT PRIMARY KEY,
    serial_no     INTEGER,
    file_no       TEXT,
    file_name     TEXT,
    impl_status   TEXT,
    link_url      TEXT,
    goto_url      TEXT,
    fields_json   TEXT NOT NULL,
    fetched_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wps_sqr_serial ON wps_standard_query_raw(serial_no);
CREATE INDEX IF NOT EXISTS idx_wps_sqr_file_no ON wps_standard_query_raw(file_no);
CREATE INDEX IF NOT EXISTS idx_wps_sqr_impl_status ON wps_standard_query_raw(impl_status);

CREATE TABLE IF NOT EXISTS wps_standard_query_fetch_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("wps_dbt_fetch")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


def first_url(fields: dict[str, Any], key: str) -> str | None:
    value = fields.get(key)
    if isinstance(value, list) and value:
        item = value[0]
        if isinstance(item, dict):
            return item.get("address") or item.get("displayText")
        return str(item)
    if isinstance(value, str):
        return value
    return None


def normalize_record(rec: dict[str, Any]) -> tuple[Any, ...]:
    fields = rec.get("fields") or {}
    return (
        rec.get("id"),
        fields.get("编号"),
        fields.get("文件编号"),
        fields.get("文件名称"),
        fields.get("实施状态"),
        first_url(fields, "链接"),
        first_url(fields, "前往"),
        json.dumps(fields, ensure_ascii=False),
        datetime.now(UTC).isoformat(),
    )


class WpsDbtClient:
    def __init__(self, webhook_url: str, token: str, logger: logging.Logger) -> None:
        self.webhook_url = webhook_url
        self.token = token
        self.logger = logger

    def call(self, argv: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
        body = json.dumps({"Context": {"argv": argv}}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "AirScript-Token": self.token,
            },
        )
        last_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                if payload.get("status") != "finished":
                    raise RuntimeError(f"任务未完成: status={payload.get('status')} error={payload.get('error')}")
                result_raw = payload.get("data", {}).get("result")
                if not isinstance(result_raw, str):
                    raise RuntimeError(f"无效 result: {result_raw!r}")
                result = json.loads(result_raw)
                if not result.get("success"):
                    raise RuntimeError(result.get("error") or "未知错误")
                return result
            except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
                last_err = exc
                wait = min(2 ** attempt, 30)
                self.logger.warning("请求失败 attempt=%s/%s: %s; %ss 后重试", attempt, MAX_RETRIES, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"WPS API 多次失败: {last_err}")

    def extract_offset_from_logs_fallback(self, argv: dict[str, Any]) -> str | None:
        """仅当脚本未返回 offset 时，从 console.log 里抠下一页游标（不可靠，作兜底）。"""
        body = json.dumps({"Context": {"argv": argv}}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "AirScript-Token": self.token,
            },
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for log in payload.get("data", {}).get("logs", []):
            for arg in log.get("args") or []:
                if isinstance(arg, str) and '"offset"' in arg:
                    match = re.search(r'"offset":"([^"]+)"', arg)
                    if match:
                        return match.group(1)
        return None


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def save_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def verify_pagination(client: WpsDbtClient, logger: logging.Logger) -> None:
    page1 = client.call({"action": "read", "limit": PAGE_SIZE})
    records1 = page1.get("records") or []
    if not records1:
        raise RuntimeError("首页无数据，请检查表格或令牌")

    offset = page1.get("offset")
    if not offset:
        offset = client.extract_offset_from_logs_fallback({"action": "read", "limit": PAGE_SIZE})
        if offset:
            logger.warning("脚本 result 未含 offset，已从日志兜底解析: %s", offset)

    if not offset:
        raise RuntimeError(
            "当前 AirScript 不支持分页（read 未返回 offset）。\n"
            "请用 scripts/wps_dbt_airscript.js (v2.1) 替换多维表脚本后重试。"
        )

    page2 = client.call({"action": "read", "limit": PAGE_SIZE, "offset": offset})
    records2 = page2.get("records") or []
    if not records2:
        raise RuntimeError("第二页无数据，分页可能异常")
    if records2[0].get("id") == records1[0].get("id"):
        raise RuntimeError(
            "第二页与第一页重复，说明脚本未处理 Context.argv.offset。\n"
            "请升级 AirScript 至 scripts/wps_dbt_airscript.js (v2.1)。"
        )
    logger.info(
        "分页校验通过: page1=%s 条, page2=%s 条, page1[0]=%s page2[0]=%s",
        len(records1),
        len(records2),
        records1[0].get("id"),
        records2[0].get("id"),
    )


def upsert_batch(conn: sqlite3.Connection, records: list[dict[str, Any]]) -> int:
    rows = [normalize_record(rec) for rec in records if rec.get("id")]
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO wps_standard_query_raw (
            record_id, serial_no, file_no, file_name, impl_status,
            link_url, goto_url, fields_json, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(record_id) DO UPDATE SET
            serial_no=excluded.serial_no,
            file_no=excluded.file_no,
            file_name=excluded.file_name,
            impl_status=excluded.impl_status,
            link_url=excluded.link_url,
            goto_url=excluded.goto_url,
            fields_json=excluded.fields_json,
            fetched_at=excluded.fetched_at
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO wps_standard_query_fetch_meta(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
    conn.commit()


def fetch_all(
    client: WpsDbtClient,
    conn: sqlite3.Connection,
    logger: logging.Logger,
    resume: bool,
    expected_total: int,
) -> None:
    state = load_state() if resume else {}
    offset = state.get("offset")
    page_no = int(state.get("page_no") or 0)
    total_saved = conn.execute("SELECT COUNT(*) FROM wps_standard_query_raw").fetchone()[0]

    if resume and offset is None and total_saved > 0:
        logger.warning("有 %s 条本地数据但无 offset 检查点，将从头重新拉取", total_saved)

    if not resume or (offset is None and total_saved == 0):
        verify_pagination(client, logger)

    start_ts = time.time()
    while True:
        page_no += 1
        argv: dict[str, Any] = {"action": "read", "limit": PAGE_SIZE}
        if offset:
            argv["offset"] = offset

        result = client.call(argv)
        records = result.get("records") or []
        saved = upsert_batch(conn, records)
        total_saved = conn.execute("SELECT COUNT(*) FROM wps_standard_query_raw").fetchone()[0]
        next_offset = result.get("offset")

        elapsed = time.time() - start_ts
        rate = total_saved / elapsed if elapsed > 0 else 0.0
        pct = (total_saved / expected_total * 100) if expected_total else 0.0
        logger.info(
            "page=%s batch=%s total=%s/%s (%.2f%%) offset_next=%s rate=%.0f/s",
            page_no,
            saved,
            total_saved,
            expected_total,
            pct,
            next_offset,
            rate,
        )

        save_state(
            {
                "offset": next_offset,
                "page_no": page_no,
                "total_saved": total_saved,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        set_meta(conn, "last_fetch_at", datetime.now(UTC).isoformat())
        set_meta(conn, "total_rows", str(total_saved))
        set_meta(conn, "expected_total", str(expected_total))

        if not records:
            logger.info("无更多记录，结束")
            break
        if not next_offset:
            logger.info("已到最后一页，结束")
            break

        offset = next_offset
        time.sleep(REQUEST_INTERVAL_SEC)

    set_meta(conn, "fetch_completed_at", datetime.now(UTC).isoformat())
    logger.info("拉取完成，共 %s 条，库文件: %s", total_saved, DB_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description="全量拉取 WPS 多维表到本地 SQLite")
    parser.add_argument("--resume", action="store_true", help="从 state 检查点续传")
    parser.add_argument("--dry-run", action="store_true", help="仅校验连通与分页")
    parser.add_argument("--expected-total", type=int, default=EXPECTED_TOTAL)
    args = parser.parse_args()

    logger = setup_logging()
    webhook_url = os.getenv("WPS_DBT_WEBHOOK_URL", DEFAULT_WEBHOOK_URL)
    token = os.getenv("WPS_AIRSCRIPT_TOKEN", DEFAULT_TOKEN).strip()
    if not token:
        raise SystemExit("WPS_AIRSCRIPT_TOKEN is required")
    client = WpsDbtClient(webhook_url, token, logger)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
        if args.dry_run:
            verify_pagination(client, logger)
            sample = client.call({"action": "read", "limit": 3})
            logger.info("dry-run OK, sample=%s", json.dumps(sample.get("records", [])[:1], ensure_ascii=False)[:500])
            return
        fetch_all(client, conn, logger, resume=args.resume, expected_total=args.expected_total)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
