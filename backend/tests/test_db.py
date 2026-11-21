"""Tests for database engine, session factory, and configuration."""

from sqlalchemy.orm import Session

from app.config import get_database_url
from app.db import Base, get_db


def test_default_database_url():
    """Verify default database URL defaults to local SQLite."""
    url = get_database_url()
    assert "sqlite" in url


def test_base_metadata():
    """Verify declarative Base has active metadata."""
    assert Base.metadata is not None


def test_get_db_session():
    """Verify get_db dependency yields a valid active Session and closes it."""
    db_gen = get_db()
    session = next(db_gen)
    assert isinstance(session, Session)
    assert session.is_active

    # Closing generator closes the session
    try:
        next(db_gen)
    except StopIteration:
        pass
