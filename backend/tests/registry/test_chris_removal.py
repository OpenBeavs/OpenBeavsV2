"""Chris is the orchestrator, not a registered agent.

Covers the seeds (neither may insert him), the ``d4f1b8a2c967`` migration that
deletes the row the early seed created, and the behavior around his absence:
nothing routes to him and his discovery card still works. Every database here is
a disposable SQLite file or in-memory database.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.db.seed_agents import INITIAL_AGENTS, seed_agents
from app.models import Agent
from app.registry.service import routable_agents
from tests.registry.test_migration import alembic_config

BACKEND = Path(__file__).resolve().parents[2]
SEED_SQL = BACKEND.parent / "docs/db_docs/seed_agents.sql"
REGISTRY_REVISION = "a7c3e91d5b02"
CHRIS_REVISION = "d4f1b8a2c967"
OSU_ID = "8f695b47-27a7-4ce7-9932-975fc618ba1d"


class TestSeedsDoNotInsertChris:
    def test_python_seed_has_no_chris(self) -> None:
        assert "chris" not in {agent["id"] for agent in INITIAL_AGENTS}
        assert "chris" not in {agent["name"].lower() for agent in INITIAL_AGENTS}

    def test_sql_seed_has_no_chris(self) -> None:
        sql = SEED_SQL.read_text().lower()
        assert "'chris'" not in sql
        assert "/chris/" not in sql

    def test_seeding_a_database_creates_no_chris_row(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
        monkeypatch.setattr("app.db.seed_agents.SessionLocal", factory)
        seed_agents()
        assert db.get(Agent, "chris") is None
        assert db.get(Agent, OSU_ID) is not None


class TestMigrationChain:
    def test_it_follows_the_registry_migration_and_is_the_only_head(self) -> None:
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        script = ScriptDirectory.from_config(config)
        assert script.get_heads() == [CHRIS_REVISION]
        assert script.get_revision(CHRIS_REVISION).down_revision == REGISTRY_REVISION

    def test_previous_migrations_are_unchanged(self) -> None:
        """The registry migration still ends with the same shape it always had."""
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        script = ScriptDirectory.from_config(config)
        assert script.get_revision(REGISTRY_REVISION).down_revision == "5f055aea1c94"


def _enable_foreign_keys(dbapi_connection, _record) -> None:
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


@pytest.fixture(params=[False, True], ids=["fk-off", "fk-on"])
def enforce_foreign_keys(request: pytest.FixtureRequest):
    """Run with SQLite foreign keys off (its default) and on (like PostgreSQL).

    The listener is global so it also covers the engine Alembic creates itself.
    """
    if request.param:
        event.listen(Engine, "connect", _enable_foreign_keys)
    yield request.param
    if request.param:
        event.remove(Engine, "connect", _enable_foreign_keys)


def build_database(url: str, monkeypatch: pytest.MonkeyPatch):
    """Create a disposable database at the registry revision holding Chris data."""
    assert url.startswith("sqlite:///"), (
        "destructive tests need a disposable SQLite file"
    )
    config = alembic_config(url, monkeypatch)
    command.upgrade(config, REGISTRY_REVISION)
    engine = create_engine(url)
    agent = (
        "INSERT INTO agents (id, name, endpoint_url, card_url, trust_tier, is_active, "
        "is_featured, status, created_at, updated_at) VALUES "
        "(:id, :name, :endpoint, :card, 'public', 1, 0, 'approved', 1, 1)"
    )
    chat = (
        "INSERT INTO chats (id, agent_id, session_type, created_at, updated_at) "
        "VALUES (:id, :agent, 'guest', 1, 1)"
    )
    message = (
        "INSERT INTO messages (id, chat_id, sender_type, content, created_at) "
        "VALUES (:id, :chat, 'user', :content, 1)"
    )
    with engine.begin() as connection:
        for row in (
            {
                "id": "chris",
                "name": "Chris",
                "endpoint": "/chris/message",
                "card": "/c",
            },
            {
                "id": "osu",
                "name": "OSU",
                "endpoint": "https://o.test/",
                "card": "https://o.test/c",
            },
        ):
            connection.execute(text(agent), row)
        connection.execute(text(chat), {"id": "chat-chris", "agent": "chris"})
        connection.execute(text(chat), {"id": "chat-osu", "agent": "osu"})
        connection.execute(text(chat), {"id": "chat-none", "agent": None})
        connection.execute(
            text(message), {"id": "m1", "chat": "chat-chris", "content": "hello"}
        )
        connection.execute(
            text(message), {"id": "m2", "chat": "chat-osu", "content": "hi osu"}
        )
    return config, engine


def rows(engine, query: str):
    with engine.connect() as connection:
        return connection.execute(text(query)).all()


class TestRemovalMigration:
    def test_deletes_only_chris_and_keeps_every_chat_and_message(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        enforce_foreign_keys: bool,
    ) -> None:
        url = f"sqlite:///{(tmp_path / 'removal.db').as_posix()}"
        config, engine = build_database(url, monkeypatch)

        command.upgrade(config, "head")

        assert rows(engine, "SELECT id FROM agents") == [("osu",)]
        # Chats survive; the one that pointed at Chris is detached, others unchanged.
        assert rows(engine, "SELECT id, agent_id FROM chats ORDER BY id") == [
            ("chat-chris", None),
            ("chat-none", None),
            ("chat-osu", "osu"),
        ]
        assert rows(engine, "SELECT id, chat_id FROM messages ORDER BY id") == [
            ("m1", "chat-chris"),
            ("m2", "chat-osu"),
        ]
        assert rows(engine, "SELECT version_num FROM alembic_version") == [
            (CHRIS_REVISION,)
        ]

    def test_is_safe_when_chris_is_already_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url = f"sqlite:///{(tmp_path / 'absent.db').as_posix()}"
        config = alembic_config(url, monkeypatch)
        command.upgrade(config, "head")  # fresh database: no Chris row ever existed
        command.downgrade(config, REGISTRY_REVISION)
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM agents WHERE id = 'chris'"))

        command.upgrade(config, "head")

        assert rows(engine, "SELECT id FROM agents WHERE id = 'chris'") == []

    def test_downgrade_restores_the_seeded_row_and_reupgrade_removes_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url = f"sqlite:///{(tmp_path / 'roundtrip.db').as_posix()}"
        config, engine = build_database(url, monkeypatch)
        command.upgrade(config, "head")

        command.downgrade(config, REGISTRY_REVISION)
        restored = rows(
            engine,
            "SELECT id, name, endpoint_url, card_url, trust_tier, is_active, "
            "is_featured, status FROM agents WHERE id = 'chris'",
        )
        assert len(restored) == 1
        (cid, name, endpoint, card, tier, active, featured, status) = restored[0]
        assert (cid, name, endpoint, card) == (
            "chris",
            "Chris",
            "/chris/message",
            "/chris/.well-known/agent.json",
        )
        assert (tier, active, featured, status) == ("public", 1, 1, "approved")
        # The JSON columns hold real JSON the application can read back.
        db = sessionmaker(bind=engine)()
        agent = db.get(Agent, "chris")
        assert agent.skills[0]["id"] == "route"
        assert agent.capabilities == {"streaming": True}
        db.close()
        # The downgrade cannot know which chats pointed at Chris.
        assert rows(engine, "SELECT agent_id FROM chats WHERE id = 'chat-chris'") == [
            (None,)
        ]

        command.upgrade(config, "head")
        assert rows(engine, "SELECT id FROM agents WHERE id = 'chris'") == []
        assert rows(engine, "SELECT id FROM agents WHERE id = 'osu'") == [("osu",)]

    def test_downgrade_does_not_overwrite_an_existing_chris_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url = f"sqlite:///{(tmp_path / 'existing.db').as_posix()}"
        config, engine = build_database(url, monkeypatch)
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agents (id, name, endpoint_url, trust_tier, is_active, "
                    "is_featured, status, created_at, updated_at) VALUES "
                    "('chris', 'Custom Chris', '/x', 'public', 1, 0, 'approved', 1, 1)"
                )
            )

        command.downgrade(config, REGISTRY_REVISION)

        assert rows(engine, "SELECT name FROM agents WHERE id = 'chris'") == [
            ("Custom Chris",)
        ]

    def test_postgres_upgrade_sql(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = alembic_config(
            "postgresql://user:placeholder@localhost/openbeavs_v2", monkeypatch
        )
        command.upgrade(config, f"{REGISTRY_REVISION}:{CHRIS_REVISION}", sql=True)
        sql = capsys.readouterr().out
        assert "UPDATE chats SET agent_id=NULL WHERE chats.agent_id = 'chris'" in sql
        assert "DELETE FROM agents WHERE agents.id = 'chris'" in sql
        assert sql.index("UPDATE chats") < sql.index("DELETE FROM agents")
        # Nothing else in the table is addressed.
        assert sql.count("DELETE FROM") == 1

    def test_postgres_downgrade_sql_renders_json_literals(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = alembic_config(
            "postgresql://user:placeholder@localhost/openbeavs_v2", monkeypatch
        )
        command.downgrade(config, f"{CHRIS_REVISION}:{REGISTRY_REVISION}", sql=True)
        sql = capsys.readouterr().out
        assert "INSERT INTO agents" in sql
        assert "CAST('[{" in sql and "AS JSON)" in sql
        assert "ON CONFLICT (id) DO NOTHING" in sql


class TestChrisIsStillAvailableButNotRegistered:
    def test_nothing_routes_to_a_leftover_chris_row(self, db: Session) -> None:
        """A database that has not run the migration yet stays safe."""
        db.add(
            Agent(
                id="chris",
                name="Chris",
                endpoint_url="/chris/message",
                trust_tier="public",
                is_active=True,
                is_featured=False,
                status="approved",
                created_at=1,
                updated_at=1,
            )
        )
        db.commit()
        assert "chris" not in {agent.id for agent in routable_agents(db)}

    def test_agents_listing_does_not_include_chris(
        self, client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
        monkeypatch.setattr("app.db.seed_agents.SessionLocal", factory)
        seed_agents()
        listed = client.get("/chat/agents").json()
        ids = {agent["id"] for agent in listed}
        assert OSU_ID in ids
        assert "chris" not in ids

    def test_discovery_card_is_served_by_code_without_a_database_row(
        self, client: TestClient, db: Session
    ) -> None:
        assert db.get(Agent, "chris") is None
        with client:
            response = client.get("/chris/a2a/.well-known/agent-card.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "chris"
        assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
        assert card["skills"]
