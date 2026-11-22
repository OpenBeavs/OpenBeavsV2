"""The tests' databases: SQLite by default, PostgreSQL when the caller supplies one.

The chat system and the agent registry each own their tables (``app.db.base``). Every
test that needs an owner's tables gets them from here, freshly created and empty.

With nothing set, each call returns a new SQLite database, so the suite needs no
server. To run the same tests against PostgreSQL, prepare a server with
``shared-resources/postgres/owners.sql`` and set:

``TEST_CHAT_SYSTEM_DATABASE_URL``
    A URL that signs in as the ``chat_system`` login.
``TEST_REGISTRY_DATABASE_URL``
    A URL that signs in as the ``registry`` login.

Each owner's tables are then created over a connection signed in as that owner, whose
``search_path`` places them in its own schema, and each owner's code reaches the server
only as its own login. A test that runs both owners in one process gets one engine per
owner, so a query from one owner's code into the other's tables fails there as it would
between two deployed services. Either variable may be set without the other.

The owner's tables are dropped and created again for every test. Point these variables
only at a database kept for testing.

The migration tests keep to SQLite files of their own in either case: one migration
history still creates both owners' tables, which neither login may do.
"""

import os
from pathlib import Path

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.pool import NullPool, StaticPool

from app.db.base import ChatSystemBase, RegistryBase

CHAT_SYSTEM_URL_VARIABLE = "TEST_CHAT_SYSTEM_DATABASE_URL"
REGISTRY_URL_VARIABLE = "TEST_REGISTRY_DATABASE_URL"


def chat_system_engine(sqlite_file: Path | None = None) -> Engine:
    """An engine on a database holding the chat system's tables, empty."""
    return _owner_engine(ChatSystemBase.metadata, CHAT_SYSTEM_URL_VARIABLE, sqlite_file)


def registry_engine(sqlite_file: Path | None = None) -> Engine:
    """An engine on a database holding the agent registry's tables, empty."""
    return _owner_engine(RegistryBase.metadata, REGISTRY_URL_VARIABLE, sqlite_file)


def _owner_engine(
    metadata: MetaData, url_variable: str, sqlite_file: Path | None
) -> Engine:
    """Create one owner's tables where the environment says, or in SQLite.

    ``sqlite_file`` chooses a file over the default in-memory database, for tests that
    read from several threads at once. PostgreSQL ignores it.
    """
    url = os.environ.get(url_variable, "").strip()
    if url:
        # No pool: a connection a test leaves checked in must not outlive the test.
        engine = create_engine(url, poolclass=NullPool)
        metadata.drop_all(bind=engine)  # whatever the previous test left
    elif sqlite_file is None:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(
            f"sqlite:///{sqlite_file.as_posix()}",
            connect_args={"check_same_thread": False},
        )
    metadata.create_all(bind=engine)
    return engine
