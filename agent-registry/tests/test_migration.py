"""The registry's migration history: it creates the ``agents`` table the model describes.

These tests prove the history has one head, that the table it creates matches the
model, keeps ``status`` without a default and one registration per card URL, that the
downgrade removes it, and that the PostgreSQL DDL renders. Every database here is a
disposable SQLite file.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from agent_registry.models import Agent

PACKAGE = Path(__file__).resolve().parents[1]
HEAD_REVISION = "182d32a2edcd"  # creates the agents table
REVIEW_COLUMNS = {"status", "submitted_by", "reviewed_by", "reviewed_at", "review_note"}


def alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Alembic settings pointed at ``database_url`` (read by ``migrations/env.py``)."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(PACKAGE / "alembic.ini"))
    config.set_main_option("script_location", str(PACKAGE / "migrations"))
    return config


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"


def test_there_is_a_single_migration_head() -> None:
    config = Config(str(PACKAGE / "alembic.ini"))
    config.set_main_option("script_location", str(PACKAGE / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD_REVISION]


def test_upgraded_table_matches_the_model(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command.upgrade(alembic_config(sqlite_url, monkeypatch), "head")
    inspector = inspect(create_engine(sqlite_url))

    assert set(inspector.get_table_names()) == {"agents", "alembic_version"}
    migrated = {c["name"]: c for c in inspector.get_columns("agents")}
    model = {c.name: c for c in Agent.__table__.columns}
    assert set(migrated) == set(model)
    for name, column in model.items():
        assert migrated[name]["nullable"] == column.nullable, name

    assert REVIEW_COLUMNS <= set(migrated)
    uniques = {
        u["name"]: u["column_names"] for u in inspector.get_unique_constraints("agents")
    }
    assert uniques.get("uq_agents_card_url") == ["card_url"]


def test_status_has_no_default_so_new_rows_must_choose(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command.upgrade(alembic_config(sqlite_url, monkeypatch), "head")
    columns = {
        c["name"]: c for c in inspect(create_engine(sqlite_url)).get_columns("agents")
    }
    assert columns["status"]["default"] is None


def test_card_url_is_unique_but_several_null_card_urls_are_allowed(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command.upgrade(alembic_config(sqlite_url, monkeypatch), "head")
    insert = (
        "INSERT INTO agents (id, name, endpoint_url, card_url, trust_tier, is_active, "
        "is_featured, status, created_at, updated_at) VALUES "
        "(:id, 'A', 'https://a.test/', :card, 'public', 1, 0, 'approved', 1, 1)"
    )
    engine = create_engine(sqlite_url)
    with engine.begin() as connection:
        connection.execute(text(insert), {"id": "1", "card": None})
        connection.execute(text(insert), {"id": "2", "card": None})
        connection.execute(text(insert), {"id": "3", "card": "https://a.test/card"})
    with pytest.raises(Exception, match="UNIQUE"), engine.begin() as connection:
        connection.execute(text(insert), {"id": "4", "card": "https://a.test/card"})


def test_downgrade_removes_the_agents_table(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = alembic_config(sqlite_url, monkeypatch)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    assert "agents" not in inspect(create_engine(sqlite_url)).get_table_names()


def test_postgres_ddl_renders_without_a_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Generate the SQL Cloud SQL would run (no connection is made)."""
    url = "postgresql+psycopg2://user:placeholder@localhost/openbeavs"
    config = alembic_config(url, monkeypatch)
    command.upgrade(config, HEAD_REVISION, sql=True)
    sql = capsys.readouterr().out

    assert "CREATE TABLE agents (" in sql
    assert "status VARCHAR(32) NOT NULL," in sql
    assert "CONSTRAINT uq_agents_card_url UNIQUE (card_url)" in sql
    for column in REVIEW_COLUMNS - {"status"}:
        assert f"\n    {column} " in sql
    # The registry's history creates its own table and no other.
    assert sql.count("CREATE TABLE") == 2  # agents, and alembic_version
