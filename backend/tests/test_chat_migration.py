"""The migration that removes the foreign key from ``chats`` to ``agents``.

The chats table keeps ``agent_id`` as a plain string, so the chat tables hold no
reference into the agent registry's table. These tests prove the upgrade keeps every
chat and message, matches the model, reverses cleanly, and renders valid PostgreSQL.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine

from alembic import command
from app.models import Chat

BACKEND = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "d4f1b8a2c967"
REVISION = "e6b2c4a9f815"
POSTGRES_URL = "postgresql://user:placeholder@localhost/openbeavs_v2"


@pytest.fixture(autouse=True)
def app_loggers_stay_enabled() -> Iterator[None]:
    """Undo Alembic's ``fileConfig``, which disables every logger that already exists.

    Without this, a log assertion in a test that runs later passes or fails by test
    order.
    """
    yield
    for name, logger in logging.Logger.manager.loggerDict.items():
        if name.startswith("app.") and isinstance(logger, logging.Logger):
            logger.disabled = False


def alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Alembic settings pointed at ``database_url`` (read by ``alembic/env.py``)."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def build_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A disposable database at the previous revision, holding a routed chat."""
    url = f"sqlite:///{(tmp_path / 'chat-migration.db').as_posix()}"
    config = alembic_config(url, monkeypatch)
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agents (id, name, endpoint_url, trust_tier, is_active, "
                "is_featured, status, created_at, updated_at) VALUES "
                "('osu', 'OSU', 'https://o.test/', 'public', 1, 0, 'approved', 1, 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO chats (id, agent_id, session_type, created_at, updated_at) "
                "VALUES ('chat-osu', 'osu', 'guest', 1, 1), "
                "('chat-none', NULL, 'guest', 1, 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO messages (id, chat_id, sender_type, content, created_at) "
                "VALUES ('m1', 'chat-osu', 'user', 'hello', 1)"
            )
        )
    return config, engine


def rows(engine, query: str):
    with engine.connect() as connection:
        return connection.execute(text(query)).all()


def referred_tables(engine) -> set[str]:
    """The tables that ``chats`` holds a foreign key into."""
    return {key["referred_table"] for key in inspect(engine).get_foreign_keys("chats")}


def test_upgrade_drops_the_foreign_key_and_keeps_every_chat_and_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, engine = build_database(tmp_path, monkeypatch)
    assert referred_tables(engine) == {"agents", "users"}

    command.upgrade(config, REVISION)

    assert referred_tables(engine) == {"users"}
    assert rows(engine, "SELECT id, agent_id FROM chats ORDER BY id") == [
        ("chat-none", None),
        ("chat-osu", "osu"),
    ]
    assert rows(engine, "SELECT id, chat_id FROM messages") == [("m1", "chat-osu")]
    assert "ix_chats_agent_id" in {
        index["name"] for index in inspect(engine).get_indexes("chats")
    }


def test_upgraded_chats_table_matches_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, engine = build_database(tmp_path, monkeypatch)
    command.upgrade(config, REVISION)

    migrated = {c["name"]: c for c in inspect(engine).get_columns("chats")}
    model = {c.name: c for c in Chat.__table__.columns}
    assert set(migrated) == set(model)
    for name, column in model.items():
        assert migrated[name]["nullable"] == column.nullable, name
    assert referred_tables(engine) == {
        key.column.table.name for key in Chat.__table__.foreign_keys
    }


def test_a_chat_may_name_an_agent_the_chat_tables_cannot_see(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With enforcement on, as PostgreSQL has it, an unknown agent id is accepted."""
    config, engine = build_database(tmp_path, monkeypatch)
    command.upgrade(config, REVISION)

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


def test_downgrade_restores_the_foreign_key_and_detaches_unknown_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, engine = build_database(tmp_path, monkeypatch)
    command.upgrade(config, REVISION)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chats (id, agent_id, session_type, created_at, updated_at) "
                "VALUES ('chat-orphan', 'no-such-agent', 'guest', 1, 1)"
            )
        )

    command.downgrade(config, PREVIOUS_REVISION)

    assert referred_tables(engine) == {"agents", "users"}
    assert rows(engine, "SELECT id, agent_id FROM chats ORDER BY id") == [
        ("chat-none", None),
        ("chat-orphan", None),
        ("chat-osu", "osu"),
    ]
    assert rows(engine, "SELECT id FROM messages") == [("m1",)]

    command.upgrade(config, REVISION)
    assert referred_tables(engine) == {"users"}


def _enable_foreign_keys(dbapi_connection, _record) -> None:
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


def test_sqlite_refuses_to_rebuild_the_table_with_enforcement_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rebuilding ``chats`` with enforcement on would cascade and delete messages."""
    config, engine = build_database(tmp_path, monkeypatch)
    engine.dispose()

    # The listener is global so it also covers the engine Alembic creates itself.
    event.listen(Engine, "connect", _enable_foreign_keys)
    try:
        with pytest.raises(RuntimeError, match="foreign-key enforcement is on"):
            command.upgrade(config, REVISION)
    finally:
        event.remove(Engine, "connect", _enable_foreign_keys)
        engine.dispose()

    assert rows(engine, "SELECT id FROM messages") == [("m1",)]
    assert referred_tables(engine) == {"agents", "users"}
    assert rows(engine, "SELECT version_num FROM alembic_version") == [
        (PREVIOUS_REVISION,)
    ]


def test_postgres_upgrade_sql(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Generate the SQL PostgreSQL would run (no connection is made)."""
    config = alembic_config(POSTGRES_URL, monkeypatch)
    command.upgrade(config, f"{PREVIOUS_REVISION}:{REVISION}", sql=True)
    sql = capsys.readouterr().out
    assert "ALTER TABLE chats DROP CONSTRAINT IF EXISTS chats_agent_id_fkey" in sql
    assert "DROP TABLE" not in sql and "DROP COLUMN" not in sql
    assert "DROP INDEX" not in sql


def test_postgres_downgrade_sql(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = alembic_config(POSTGRES_URL, monkeypatch)
    command.downgrade(config, f"{REVISION}:{PREVIOUS_REVISION}", sql=True)
    sql = capsys.readouterr().out
    assert "UPDATE chats SET agent_id=NULL" in sql
    assert (
        "ALTER TABLE chats ADD CONSTRAINT chats_agent_id_fkey FOREIGN KEY(agent_id) "
        "REFERENCES agents (id) ON DELETE SET NULL" in sql
    )
    assert sql.index("UPDATE chats") < sql.index("ADD CONSTRAINT")
