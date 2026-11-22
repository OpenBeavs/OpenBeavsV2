"""Chris is the orchestrator, not a registered agent.

Covers the seeds (neither may insert him) and the registry's behavior around his
absence: nothing routes to him, even from a row an old database still holds. Each test
gets a fresh database from the ``db`` fixture.
"""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from agent_registry.db.seed_agents import INITIAL_AGENTS, seed_agents
from agent_registry.models import Agent
from agent_registry.service import routable_agents

SEED_SQL = Path(__file__).resolve().parents[1] / "scripts/seed_agents.sql"
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
        monkeypatch.setattr("agent_registry.db.seed_agents.SessionLocal", factory)
        seed_agents()
        assert db.get(Agent, "chris") is None
        assert db.get(Agent, OSU_ID) is not None


class TestChrisIsStillAvailableButNotRegistered:
    def test_nothing_routes_to_a_leftover_chris_row(self, db: Session) -> None:
        """A row left by the early seed, in a database never cleaned of it, stays safe."""
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
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
        monkeypatch.setattr("agent_registry.db.seed_agents.SessionLocal", factory)
        seed_agents()
        ids = {agent.id for agent in routable_agents(db)}
        assert OSU_ID in ids
        assert "chris" not in ids
