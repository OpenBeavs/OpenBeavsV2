"""PostgreSQL keeps each owner of data out of the other's schema.

``shared-resources/postgres/owners.sql`` gives the chat system and the agent registry
one login and one schema each. These tests sign in as each login and show that it
works in its own schema and is refused on the other's, whether it reads, writes,
creates a table, or tries to grant itself the right.

They need a PostgreSQL server that the caller has started and prepared with
``owners.sql``, and reach it through the two URLs ``tests/databases.py`` describes:
``TEST_CHAT_SYSTEM_DATABASE_URL`` and ``TEST_REGISTRY_DATABASE_URL``. They never start
or stop a server. ``shared-resources/postgres/README.md`` has the commands.

When either URL is unset every test here is skipped, so the suite still passes with
no server. A skip means the boundary was not checked in that run: SQLite has no
logins or grants to check.
"""

import os
from collections.abc import Iterator

import pytest
from agent_registry.service import routable_agents
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.models import User
from tests.databases import (
    CHAT_SYSTEM_URL_VARIABLE,
    REGISTRY_URL_VARIABLE,
    chat_system_engine,
    registry_engine,
)

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get(CHAT_SYSTEM_URL_VARIABLE, "").strip()
        and os.environ.get(REGISTRY_URL_VARIABLE, "").strip()
    ),
    reason=(
        f"needs {CHAT_SYSTEM_URL_VARIABLE} and {REGISTRY_URL_VARIABLE}: a PostgreSQL "
        "server prepared with shared-resources/postgres/owners.sql"
    ),
)

# PostgreSQL's error codes (SQLSTATE) for the two ways a crossing fails.
INSUFFICIENT_PRIVILEGE = "42501"
UNDEFINED_TABLE = "42P01"

# Each login, the other owner's schema, and a table the other owner keeps there.
CROSSINGS = [
    ("chat_system", "registry", "agents"),
    ("registry", "chat_system", "users"),
]


@pytest.fixture
def engines() -> Iterator[dict[str, Engine]]:
    """One engine per login, with each owner's tables created by that login."""
    by_login = {"chat_system": chat_system_engine(), "registry": registry_engine()}
    yield by_login
    for engine in by_login.values():
        engine.dispose()


def error_code(engine: Engine, statement: str) -> str:
    """Run a statement that PostgreSQL must reject, and return its error code."""
    with engine.connect() as connection, pytest.raises(ProgrammingError) as refusal:
        connection.execute(text(statement))
    return refusal.value.orig.pgcode


@pytest.mark.parametrize(
    ("login", "table"), [("chat_system", "users"), ("registry", "agents")]
)
def test_a_login_works_in_its_own_schema(
    engines: dict[str, Engine], login: str, table: str
) -> None:
    """The login is the one named, and its tables sit in the schema of the same name."""
    with engines[login].connect() as connection:
        assert connection.scalar(text("SELECT current_user")) == login
        assert connection.scalar(text("SELECT current_schema()")) == login
        owner = connection.scalar(
            text(
                "SELECT tableowner FROM pg_tables "
                "WHERE schemaname = :schema AND tablename = :table"
            ),
            {"schema": login, "table": table},
        )
        assert owner == login
        assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0


@pytest.mark.parametrize(("login", "other", "table"), CROSSINGS)
class TestALoginIsRefusedOnTheOtherSchema:
    def test_it_cannot_read_a_table_there(
        self, engines: dict[str, Engine], login: str, other: str, table: str
    ) -> None:
        code = error_code(engines[login], f"SELECT * FROM {other}.{table}")
        assert code == INSUFFICIENT_PRIVILEGE

    def test_it_cannot_write_to_a_table_there(
        self, engines: dict[str, Engine], login: str, other: str, table: str
    ) -> None:
        code = error_code(engines[login], f"DELETE FROM {other}.{table}")
        assert code == INSUFFICIENT_PRIVILEGE

    def test_it_cannot_create_a_table_there(
        self, engines: dict[str, Engine], login: str, other: str, table: str
    ) -> None:
        code = error_code(engines[login], f"CREATE TABLE {other}.intruder (id integer)")
        assert code == INSUFFICIENT_PRIVILEGE

    def test_it_cannot_grant_itself_the_right(
        self, engines: dict[str, Engine], login: str, other: str, table: str
    ) -> None:
        code = error_code(engines[login], f"GRANT USAGE ON SCHEMA {other} TO {login}")
        assert code == INSUFFICIENT_PRIVILEGE

    def test_a_bare_table_name_does_not_reach_it(
        self, engines: dict[str, Engine], login: str, other: str, table: str
    ) -> None:
        """The models name no schema, so the other owner's table is simply not found."""
        assert error_code(engines[login], f"SELECT * FROM {table}") == UNDEFINED_TABLE


@pytest.mark.parametrize("login", ["chat_system", "registry"])
def test_no_login_can_create_a_table_in_the_public_schema(
    engines: dict[str, Engine], login: str
) -> None:
    """The schema every database starts with is closed, so the owners cannot meet there."""
    code = error_code(engines[login], "CREATE TABLE public.shared (id integer)")
    assert code == INSUFFICIENT_PRIVILEGE


def test_the_registry_query_fails_for_the_chat_system_login(
    engines: dict[str, Engine],
) -> None:
    """Chat system code that still read the agents table would fail like this."""
    with (
        Session(engines["chat_system"]) as db,
        pytest.raises(ProgrammingError) as failure,
    ):
        routable_agents(db)
    assert failure.value.orig.pgcode == UNDEFINED_TABLE


def test_a_chat_system_query_fails_for_the_registry_login(
    engines: dict[str, Engine],
) -> None:
    """Registry code that read the users table would fail like this."""
    with Session(engines["registry"]) as db, pytest.raises(ProgrammingError) as failure:
        db.query(User).count()
    assert failure.value.orig.pgcode == UNDEFINED_TABLE
