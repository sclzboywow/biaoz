#!/bin/sh
set -e
cd /app

VERSION="$(alembic current 2>/dev/null | grep -oE '202[0-9]+_[0-9]+' | tail -1 || true)"
HEAD="20260614_0011"

if [ "$VERSION" = "$HEAD" ]; then
  echo "Alembic already at head ($HEAD)"
elif [ -z "$VERSION" ]; then
  echo "Fresh database: apply baseline then stamp head"
  alembic upgrade 20260528_0001
  alembic stamp "$HEAD"
elif [ "$VERSION" = "20260528_0001" ]; then
  echo "Baseline applied; stamp remaining revisions"
  alembic stamp "$HEAD"
else
  echo "Upgrading database to head"
  alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
