# Production Data Layer

- All environments use PostgreSQL. Non-PostgreSQL `DATABASE_URL` values are rejected at startup.
- Database schema and indexes are managed by Alembic. Run `alembic upgrade head` before starting the API.
- Docker startup runs `alembic upgrade head` automatically before `uvicorn`.
- Large list APIs use cursor/keyset pagination through `next_cursor` and `has_more`.
- URL batch checks stream source IDs in batches instead of loading all IDs into memory.
- Standard file matching runs incrementally with `cursor` and `batch_size`.
- Low-value successful `check_logs` are archived by `scripts/archive_operational_logs.py`; register the monthly task with `scripts/register-log-archive-task.ps1`.
