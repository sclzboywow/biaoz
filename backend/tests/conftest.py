import os

from app.config import get_settings

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://biaoz:biaoz@localhost:5432/biaoz",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
get_settings.cache_clear()

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)


@pytest.fixture()
def no_index_matches(monkeypatch):
    """Avoid fuzzy matches against the shared PostgreSQL dataset during unit tests."""
    monkeypatch.setattr(
        "app.document_classification_service.search_trusted_sources_sliced",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "app.document_classification_service.match_existing_documents_for_classification",
        lambda *args, **kwargs: [],
    )


@pytest.fixture()
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
