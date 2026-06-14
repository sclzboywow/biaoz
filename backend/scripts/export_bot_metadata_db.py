#!/usr/bin/env python3
"""Export a slim PostgreSQL dump for QQ bot (search + baidu share only)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psycopg

DSN = "postgresql://biaoz:biaoz@localhost:5432/biaoz"
EXPORT_SCHEMA = "bot_export"
PG_BIN = Path(r"C:\Program Files\PostgreSQL\17\bin")
PG_DUMP = PG_BIN / "pg_dump.exe"

SR_COLUMNS = (
    "id",
    "standard_no",
    "normalized_standard_no",
    "standard_name",
    "resource_type",
    "keywords",
)
DOC_COLUMNS = (
    "id",
    "standard_no",
    "normalized_standard_no",
    "title",
    "category",
    "created_at",
    "updated_at",
)
DV_COLUMNS = (
    "id",
    "document_id",
    "version_no",
    "is_current",
    "file_path",
    "remark",
    "created_at",
)


def recreate_export_schema(conn: psycopg.Connection) -> None:
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {EXPORT_SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {EXPORT_SCHEMA}")


def build_export_tables(conn: psycopg.Connection) -> dict[str, int]:
    sr_cols = ", ".join(SR_COLUMNS)
    doc_cols = ", ".join(DOC_COLUMNS)
    dv_cols = ", ".join(DV_COLUMNS)
    counts: dict[str, int] = {}

    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE {EXPORT_SCHEMA}.documents (
                id INTEGER PRIMARY KEY,
                standard_no VARCHAR(120),
                normalized_standard_no VARCHAR(160),
                title VARCHAR(500),
                category VARCHAR(120),
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            f"""
            INSERT INTO {EXPORT_SCHEMA}.documents ({doc_cols})
            SELECT {doc_cols}
            FROM public.documents
            """
        )
        cur.execute(f"SELECT count(*) FROM {EXPORT_SCHEMA}.documents")
        counts["documents"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            CREATE TABLE {EXPORT_SCHEMA}.standard_resources (
                id INTEGER PRIMARY KEY,
                standard_no VARCHAR(120),
                normalized_standard_no VARCHAR(160),
                standard_name VARCHAR(500) NOT NULL,
                resource_type VARCHAR(120),
                keywords TEXT
            )
            """
        )
        cur.execute(
            f"""
            INSERT INTO {EXPORT_SCHEMA}.standard_resources ({sr_cols})
            SELECT {sr_cols}
            FROM public.standard_resources
            WHERE standard_no IS NOT NULL AND BTRIM(standard_no) <> ''
            """
        )
        cur.execute(f"SELECT count(*) FROM {EXPORT_SCHEMA}.standard_resources")
        counts["standard_resources"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            CREATE TABLE {EXPORT_SCHEMA}.document_versions (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES {EXPORT_SCHEMA}.documents(id),
                version_no VARCHAR(80),
                is_current BOOLEAN NOT NULL DEFAULT FALSE,
                file_path TEXT,
                remark TEXT,
                created_at TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            f"""
            INSERT INTO {EXPORT_SCHEMA}.document_versions ({dv_cols})
            SELECT {", ".join(f"dv.{col}" for col in DV_COLUMNS)}
            FROM public.document_versions dv
            INNER JOIN {EXPORT_SCHEMA}.documents d ON d.id = dv.document_id
            WHERE dv.is_current IS TRUE
            """
        )
        cur.execute(f"SELECT count(*) FROM {EXPORT_SCHEMA}.document_versions")
        counts["document_versions"] = int(cur.fetchone()[0])

        cur.execute(
            f"""
            CREATE INDEX idx_sr_standard_no ON {EXPORT_SCHEMA}.standard_resources (standard_no);
            CREATE INDEX idx_sr_normalized ON {EXPORT_SCHEMA}.standard_resources (normalized_standard_no);
            CREATE INDEX idx_doc_standard_no ON {EXPORT_SCHEMA}.documents (standard_no);
            CREATE INDEX idx_doc_normalized ON {EXPORT_SCHEMA}.documents (normalized_standard_no);
            CREATE INDEX idx_dv_document_current ON {EXPORT_SCHEMA}.document_versions (document_id, is_current);
            """
        )
    return counts


def rewrite_dump_for_public_schema(raw_sql: Path, final_sql: Path) -> None:
    skip_prefixes = (
        "CREATE SCHEMA ",
        "DROP SCHEMA ",
        "\\restrict ",
        "\\unrestrict ",
    )
    out_lines: list[str] = []
    inserted_search_path = False
    for line in raw_sql.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if any(stripped.startswith(prefix) for prefix in skip_prefixes):
            continue
        if stripped == "SELECT pg_catalog.set_config('search_path', '', false);":
            out_lines.append("SELECT pg_catalog.set_config('search_path', 'public', false);")
            inserted_search_path = True
            continue
        out_lines.append(line.replace(f"{EXPORT_SCHEMA}.", "public."))
    if not inserted_search_path:
        out_lines.insert(0, "SET search_path = public;")
    final_sql.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def cleanup_export_schema(conn: psycopg.Connection) -> None:
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {EXPORT_SCHEMA} CASCADE")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export slim bot metadata database dump")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .sql path (default: logs/biaoz-bot-metadata-<ts>.sql)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    log_dir = repo_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.output or (log_dir / f"biaoz-bot-metadata-{ts}.sql")
    raw_dump = output.with_suffix(".raw.sql")

    if not PG_DUMP.exists():
        print(f"pg_dump not found: {PG_DUMP}", file=sys.stderr)
        return 1

    try:
        print(f"[1/5] build temp schema {EXPORT_SCHEMA}")
        with psycopg.connect(DSN) as conn:
            recreate_export_schema(conn)
            counts = build_export_tables(conn)
            for name, count in counts.items():
                print(f"  {name}: {count}")

        print(f"[2/5] pg_dump schema {EXPORT_SCHEMA} -> {raw_dump}")
        env = {**subprocess.os.environ, "PGPASSWORD": "biaoz"}
        subprocess.run(
            [
                str(PG_DUMP),
                "-h",
                "localhost",
                "-p",
                "5432",
                "-U",
                "biaoz",
                "-d",
                "biaoz",
                "-n",
                EXPORT_SCHEMA,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "-f",
                str(raw_dump),
            ],
            check=True,
            env=env,
        )

        print(f"[3/5] rewrite dump -> public schema: {output}")
        rewrite_dump_for_public_schema(raw_dump, output)
        raw_dump.unlink(missing_ok=True)

        size_mb = output.stat().st_size / 1024 / 1024
        print(f"[4/5] dump size: {size_mb:.1f} MB")
        print(f"[5/5] done: {output}")
        return 0
    finally:
        with psycopg.connect(DSN) as conn:
            cleanup_export_schema(conn)


if __name__ == "__main__":
    raise SystemExit(main())
