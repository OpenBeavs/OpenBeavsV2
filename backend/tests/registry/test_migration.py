"""The registry migration: safe on a database that already has agents.

The cloud database already holds the seeded production agents. These tests prove
the upgrade keeps them routable, matches the model, and renders valid Postgres DDL.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.models import Agent

BACKEND = Path(__file__).resolve().parents[2]
PREVIOUS_REVISION = "5f055aea1c94"
REGISTRY_REVISION = "a7c3e91d5b02"
NEW_COLUMNS = {"status", "submitted_by", "reviewed_by", "reviewed_at", "review_note"}


def alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Alembic settings pointed at ``database_url`` (read by ``alembic/env.py``)."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"


def test_there_is_a_single_migration_head() -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [REGISTRY_REVISION]


def test_existing_agents_stay_routable_after_upgrade(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = alembic_config(sqlite_url, monkeypatch)
    command.upgrade(config, PREVIOUS_REVISION)

    engine = create_engine(sqlite_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agents (id, name, endpoint_url, card_url, trust_tier, "
                "is_active, is_featured, created_at, updated_at) VALUES "
                "('osu', 'OSU', 'https://osu.test/', 'https://osu.test/card', "
                "'public', 1, 0, 1, 1)"
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, submitted_by, reviewed_by FROM agents WHERE id = 'osu'"
            )
        ).one()
    assert row == ("approved", None, None)


def test_upgraded_table_matches_the_model(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    command.upgrade(alembic_config(sqlite_url, monkeypatch), "head")
    inspector = inspect(create_engine(sqlite_url))

    migrated = {c["name"]: c for c in inspector.get_columns("agents")}
    model = {c.name: c for c in Agent.__table__.columns}
    assert set(migrated) == set(model)
    for name, column in model.items():
        assert migrated[name]["nullable"] == column.nullable, name

    assert NEW_COLUMNS <= set(migrated)
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


def test_downgrade_removes_the_registry_columns(
    sqlite_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = alembic_config(sqlite_url, monkeypatch)
    command.upgrade(config, "head")
    command.downgrade(config, PREVIOUS_REVISION)

    inspector = inspect(create_engine(sqlite_url))
    assert not NEW_COLUMNS & {c["name"] for c in inspector.get_columns("agents")}
    assert not inspector.get_unique_constraints("agents")


def test_postgres_ddl_renders_without_a_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Generate the SQL Cloud SQL would run (no connection is made)."""
    url = "postgresql://user:placeholder@localhost/openbeavs_v2"
    config = alembic_config(url, monkeypatch)
    command.upgrade(config, f"{PREVIOUS_REVISION}:{REGISTRY_REVISION}", sql=True)
    sql = capsys.readouterr().out

    assert (
        "ALTER TABLE agents ADD COLUMN status VARCHAR(32) DEFAULT 'approved' NOT NULL"
        in sql
    )
    assert "ALTER TABLE agents ALTER COLUMN status DROP DEFAULT" in sql
    assert (
        "ALTER TABLE agents ADD CONSTRAINT uq_agents_card_url UNIQUE (card_url)" in sql
    )
    for column in NEW_COLUMNS - {"status"}:
        assert f"ADD COLUMN {column}" in sql
