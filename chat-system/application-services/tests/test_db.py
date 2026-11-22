"""Tests for database engine, session factory, and configuration."""

from sqlalchemy.orm import Session

from application_services.config import get_database_url
from application_services.db import ChatSystemBase, get_db


def test_default_database_url():
    """Verify default database URL defaults to local SQLite."""
    url = get_database_url()
    assert "sqlite" in url


def test_base_metadata():
    """Verify the chat system's declarative base holds its tables and no others."""
    import application_services.models  # noqa: F401 (registers the models with their metadata)

    assert set(ChatSystemBase.metadata.tables) == {
        "users",
        "chats",
        "messages",
        "tickets",
    }


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
