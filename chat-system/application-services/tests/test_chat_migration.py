"""The chat system's migration history: it creates the tables the models describe.

These tests prove the history has one head, that the tables it creates match the
models and are the chat system's alone, that ``chats.agent_id`` refers to no table, that
the downgrade removes them, and that the PostgreSQL DDL renders. Every database here
is a disposable SQLite file.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from application_services.db.base import ChatSystemBase
from application_services.models import Chat

PACKAGE = Path(__file__).resolve().parents[1]
HEAD_REVISION = "34fddc6e996d"  # creates users, chats, messages and tickets
TABLES = {"users", "chats", "messages", "tickets"}
POSTGRES_URL = "postgresql+psycopg2://user:placeholder@localhost/openbeavs"


@pytest.fixture(autouse=True)
def app_loggers_stay_enabled() -> Iterator[None]:
    """Undo Alembic's ``fileConfig``, which disables every logger that already exists.

    Without this, a log assertion in a test that runs later passes or fails by test
    order.
    """
    yield
    for name, logger in logging.Logger.manager.loggerDict.items():
        if name.startswith("application_services.") and isinstance(
            logger, logging.Logger
        ):
            logger.disabled = False


def alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Alembic settings pointed at ``database_url`` (read by ``migrations/env.py``)."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(PACKAGE / "alembic.ini"))
    config.set_main_option("script_location", str(PACKAGE / "migrations"))
    return config


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'chat-migration.db').as_posix()}"


def rows(engine, query: str):
    with engine.connect() as connection:
        return connection.execute(text(query)).all()


def referred_tables(engine) -> set[str]:
    """The tables that ``chats`` holds a foreign key into."""
    return {key["referred_table"] for key in inspect(engine).get_foreign_keys("chats")}


def test_there_is_a_single_migration_head() -> None:
    config = Config(str(PACKAGE / "alembic.ini"))
    config.set_main_option("script_location", str(PACKAGE / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD_REVISION]


def test_upgraded_tables_match_the_models(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command.upgrade(alembic_config(sqlite_url, monkeypatch), "head")
    inspector = inspect(create_engine(sqlite_url))

    assert set(inspector.get_table_names()) == TABLES | {"alembic_version"}
    for table in ChatSystemBase.metadata.sorted_tables:
        migrated = {c["name"]: c for c in inspector.get_columns(table.name)}
        assert set(migrated) == {c.name for c in table.columns}, table.name
        for column in table.columns:
            assert migrated[column.name]["nullable"] == column.nullable, (
                table.name,
                column.name,
            )
        assert {i["name"] for i in inspector.get_indexes(table.name)} == {
            i.name for i in table.indexes
        }, table.name


def test_upgraded_chats_table_matches_the_model(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command.upgrade(alembic_config(sqlite_url, monkeypatch), "head")
    engine = create_engine(sqlite_url)

    migrated = {c["name"]: c for c in inspect(engine).get_columns("chats")}
    model = {c.name: c for c in Chat.__table__.columns}
    assert set(migrated) == set(model)
    for name, column in model.items():
        assert migrated[name]["nullable"] == column.nullable, name
    assert referred_tables(engine) == {
        key.column.table.name for key in Chat.__table__.foreign_keys
    }


def test_a_chat_may_name_an_agent_the_chat_tables_cannot_see(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With enforcement on, as PostgreSQL has it, an unknown agent id is accepted."""
    command.upgrade(alembic_config(sqlite_url, monkeypatch), "head")
    engine = create_engine(sqlite_url)

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(
            text(
                "INSERT INTO chats (id, agent_id, session_type, created_at, updated_at) "
                "VALUES ('chat-elsewhere', 'registered-elsewhere', 'guest', 1, 1)"
            )
        )
    assert rows(engine, "SELECT agent_id FROM chats WHERE id = 'chat-elsewhere'") == [
        ("registered-elsewhere",)
    ]


def test_downgrade_removes_the_chat_system_tables(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = alembic_config(sqlite_url, monkeypatch)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    assert set(inspect(create_engine(sqlite_url)).get_table_names()) <= {
        "alembic_version"
    }


def test_postgres_upgrade_sql(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Generate the SQL PostgreSQL would run (no connection is made)."""
    config = alembic_config(POSTGRES_URL, monkeypatch)
    command.upgrade(config, HEAD_REVISION, sql=True)
    sql = capsys.readouterr().out
    for table in TABLES:
        assert f"CREATE TABLE {table} (" in sql
    # The chat system's history creates its own tables and no other.
    assert sql.count("CREATE TABLE") == len(TABLES) + 1  # and alembic_version
    assert "agents" not in sql
    assert (
        "CONSTRAINT chats_user_id_fkey FOREIGN KEY(user_id) REFERENCES users (id) "
        "ON DELETE SET NULL" in sql
    )


def test_postgres_downgrade_sql(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = alembic_config(POSTGRES_URL, monkeypatch)
    command.downgrade(config, f"{HEAD_REVISION}:base", sql=True)
    sql = capsys.readouterr().out
    drops = [line for line in sql.splitlines() if line.startswith("DROP TABLE")]
    # A table goes only after every table that refers to it.
    assert drops == [
        "DROP TABLE messages;",
        "DROP TABLE tickets;",
        "DROP TABLE chats;",
        "DROP TABLE users;",
    ]
