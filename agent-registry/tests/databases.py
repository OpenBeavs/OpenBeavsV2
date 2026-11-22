"""The tests' database: SQLite by default, PostgreSQL when the caller supplies one.

Every test that needs the registry's tables gets them from here, freshly created and
empty. With nothing set, each call returns a new SQLite database, so the suite needs
no server. To run the same tests against PostgreSQL, prepare a server with
``shared-resources/postgres/owners.sql`` and set ``TEST_REGISTRY_DATABASE_URL`` to a
URL that signs in as the ``registry`` login. The tables are then created over a
connection signed in as that login, whose ``search_path`` places them in the
``registry`` schema.

The tables are dropped and created again for every test. Point the variable only at a
database kept for testing.

The migration tests keep to SQLite files of their own in either case.
"""

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool, StaticPool

import agent_registry.models  # noqa: F401 (registers the tables with the metadata)
from agent_registry.db.base import RegistryBase

REGISTRY_URL_VARIABLE = "TEST_REGISTRY_DATABASE_URL"


def registry_engine(sqlite_file: Path | None = None) -> Engine:
    """An engine on a database holding the agent registry's tables, empty.

    ``sqlite_file`` chooses a file over the default in-memory database, for tests that
    read from several threads at once. PostgreSQL ignores it.
    """
    metadata = RegistryBase.metadata
    url = os.environ.get(REGISTRY_URL_VARIABLE, "").strip()
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
