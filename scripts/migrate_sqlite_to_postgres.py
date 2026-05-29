from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, create_engine, text

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.database import Base  # noqa: E402
from app import models  # noqa: F401,E402


def coerce_value(value: Any, column=None) -> Any:
    if column is not None and isinstance(column.type, Boolean) and value is not None:
        return bool(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def fallback_value(row: sqlite3.Row, column) -> Any:
    value = row[column.name]
    if value is not None:
        return value
    if column.name == "created_at":
        for candidate in ("checked_at", "downloaded_at", "captured_at", "detected_at", "synced_at", "matched_at", "updated_at"):
            if candidate in row.keys() and row[candidate] is not None:
                return row[candidate]
    if column.name == "updated_at" and "created_at" in row.keys() and row["created_at"] is not None:
        return row["created_at"]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate local SQLite data into PostgreSQL.")
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--postgres", required=True)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()

    if not args.sqlite.exists():
        raise FileNotFoundError(args.sqlite)
    if not args.postgres.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("Target must be a PostgreSQL DSN.")

    sqlite_conn = sqlite3.connect(args.sqlite)
    sqlite_conn.row_factory = sqlite3.Row
    pg_engine = create_engine(args.postgres, pool_pre_ping=True)

    sorted_tables = [table for table in Base.metadata.sorted_tables if table.name != "alembic_version"]
    with pg_engine.begin() as pg:
        if args.truncate:
            table_names = ", ".join(f'"{table.name}"' for table in reversed(sorted_tables))
            if table_names:
                pg.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))

        for table in sorted_tables:
            source_columns = {
                row["name"]
                for row in sqlite_conn.execute(f"PRAGMA table_info({table.name})").fetchall()
            }
            if not source_columns:
                print(f"{table.name}=missing_source")
                continue
            insert_columns = [column for column in table.columns if column.name in source_columns]
            if not insert_columns:
                print(f"{table.name}=no_shared_columns")
                continue

            column_names = [column.name for column in insert_columns]
            placeholders = ", ".join(f":{name}" for name in column_names)
            quoted_columns = ", ".join(f'"{name}"' for name in column_names)
            insert_sql = text(f'INSERT INTO "{table.name}" ({quoted_columns}) VALUES ({placeholders})')

            count = 0
            cursor = sqlite_conn.execute(f'SELECT {", ".join(column_names)} FROM {table.name}')
            while True:
                rows = cursor.fetchmany(max(args.batch_size, 1))
                if not rows:
                    break
                payload = []
                for row in rows:
                    item = {}
                    for column in insert_columns:
                        item[column.name] = coerce_value(fallback_value(row, column), column)
                    payload.append(item)
                pg.execute(insert_sql, payload)
                count += len(payload)
            print(f"{table.name}={count}")

        for table in sorted_tables:
            if "id" in table.columns:
                pg.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                        "COALESCE((SELECT MAX(id) FROM " + f'"{table.name}"' + "), 1), "
                        "COALESCE((SELECT MAX(id) FROM " + f'"{table.name}"' + "), 0) > 0)"
                    ),
                    {"table_name": table.name},
                )

    sqlite_conn.close()


if __name__ == "__main__":
    main()
