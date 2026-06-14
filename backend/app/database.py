from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
if not settings.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
    raise RuntimeError(
        "DATABASE_URL must be PostgreSQL, "
        "for example postgresql+psycopg://user:password@host:5432/biaoz."
    )

engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
