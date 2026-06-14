"""Create biaoz_test and apply Alembic migrations (requires CREATEDB or superuser)."""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg

DEFAULT_ADMIN_URL = "postgresql://biaoz:biaoz@localhost:5432/postgres"
DEFAULT_TEST_URL = "postgresql+psycopg://biaoz:biaoz@localhost:5432/biaoz_test"
TEST_DB_NAME = "biaoz_test"


def main() -> int:
    admin_url = os.environ.get("POSTGRES_ADMIN_URL", DEFAULT_ADMIN_URL)
    test_url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_URL)

    with psycopg.connect(admin_url) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
                print(f"Created database {TEST_DB_NAME}")
            else:
                print(f"Database {TEST_DB_NAME} already exists")

    env = os.environ.copy()
    env["DATABASE_URL"] = test_url
    subprocess.run(["alembic", "upgrade", "head"], check=True, env=env)
    print(f"Migrations applied to {test_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
