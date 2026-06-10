"""
将 WPS 多维表 SQLite 快照导入 PostgreSQL 暂存表 wps_standard_query_records。

用法:
  backend/.venv/Scripts/python.exe scripts/import_wps_dbt_to_postgres.py
  backend/.venv/Scripts/python.exe scripts/import_wps_dbt_to_postgres.py --truncate
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
import os

os.chdir(BACKEND)

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app import models  # noqa: F401,E402

SQLITE_PATH = ROOT / "data" / "wps_standard_query_raw.db"
DEFAULT_BATCH = 5000


def parse_fetched_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def import_rows(sqlite_path: Path, batch_size: int, truncate: bool) -> dict[str, int]:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite 快照不存在: {sqlite_path}")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    total_source = sqlite_conn.execute("SELECT COUNT(*) FROM wps_standard_query_raw").fetchone()[0]

    stats = {"source": total_source, "inserted": 0, "batches": 0}
    start = time.time()

    with SessionLocal() as db:
        if truncate:
            db.execute(text("TRUNCATE TABLE wps_standard_query_records RESTART IDENTITY"))
            db.commit()

        cursor = sqlite_conn.execute(
            """
            SELECT record_id, serial_no, file_no, file_name, impl_status,
                   link_url, goto_url, fields_json, fetched_at
            FROM wps_standard_query_raw
            ORDER BY serial_no ASC, record_id ASC
            """
        )

        batch: list[dict] = []
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break

            for row in rows:
                batch.append(
                    {
                        "wps_record_id": row["record_id"],
                        "serial_no": row["serial_no"],
                        "file_no": row["file_no"],
                        "file_name": row["file_name"],
                        "impl_status": row["impl_status"],
                        "link_url": row["link_url"],
                        "goto_url": row["goto_url"],
                        "fields_json": row["fields_json"],
                        "wps_fetched_at": parse_fetched_at(row["fetched_at"]),
                        "source_sheet": "标准查询系统",
                        "governance_status": "pending",
                    }
                )

            db.bulk_insert_mappings(models.WpsStandardQueryRecord, batch)
            db.commit()
            stats["inserted"] += len(batch)
            stats["batches"] += 1
            elapsed = time.time() - start
            rate = stats["inserted"] / elapsed if elapsed > 0 else 0.0
            pct = stats["inserted"] / total_source * 100 if total_source else 0.0
            print(
                f"batch={stats['batches']} inserted={stats['inserted']}/{total_source} "
                f"({pct:.2f}%) rate={rate:.0f}/s"
            )
            batch.clear()

    sqlite_conn.close()
    stats["elapsed_sec"] = round(time.time() - start, 2)
    return stats


def verify() -> None:
    with SessionLocal() as db:
        total = db.execute(text("SELECT COUNT(*) FROM wps_standard_query_records")).scalar()
        minmax = db.execute(
            text("SELECT MIN(serial_no), MAX(serial_no) FROM wps_standard_query_records")
        ).one()
        status_rows = db.execute(
            text(
                """
                SELECT impl_status, COUNT(*) AS c
                FROM wps_standard_query_records
                GROUP BY impl_status
                ORDER BY c DESC
                LIMIT 5
                """
            )
        ).all()
        print(f"pg_total={total}")
        print(f"serial_no_range={minmax}")
        print("impl_status_top=", status_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import WPS SQLite snapshot into PostgreSQL")
    parser.add_argument("--sqlite", type=Path, default=SQLITE_PATH)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--truncate", action="store_true", help="清空目标表后全量导入")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if args.verify_only:
        verify()
        return

    # 确保表存在（迁移应已执行，此处兜底）
    models.WpsStandardQueryRecord.__table__.create(bind=engine, checkfirst=True)

    stats = import_rows(args.sqlite, args.batch_size, truncate=args.truncate)
    print(
        f"done source={stats['source']} inserted={stats['inserted']} "
        f"batches={stats['batches']} elapsed={stats['elapsed_sec']}s"
    )
    verify()


if __name__ == "__main__":
    main()
