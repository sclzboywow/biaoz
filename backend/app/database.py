from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
if settings.database_url.startswith("sqlite") and not settings.allow_sqlite:
    raise RuntimeError(
        "SQLite is disabled. Configure DATABASE_URL with a PostgreSQL DSN, "
        "for example postgresql+psycopg://user:password@host:5432/biaoz."
    )
if not settings.database_url.startswith(("postgresql://", "postgresql+psycopg://")) and not settings.allow_sqlite:
    raise RuntimeError("Production database must be PostgreSQL. Set ALLOW_SQLITE=true only for isolated tests.")

engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
