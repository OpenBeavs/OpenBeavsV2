"""Seeding the production agents must not undo an admin's review decisions."""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.seed_agents import INITIAL_AGENTS, seed_agents
from app.models import Agent
from app.registry.service import routable_agents

HELLO_WORLD_ID = "26b643fd-9a61-465d-b075-89ba84d503cb"
OSU_ID = "8f695b47-27a7-4ce7-9932-975fc618ba1d"


@pytest.fixture(params=["python", "sql"])
def seed(db: Session, monkeypatch: pytest.MonkeyPatch, request):
    """Run ``seed_agents`` against the test database."""
    if request.param == "sql":
        sql = (
            Path(__file__).resolve().parents[3] / "docs/db_docs/seed_agents.sql"
        ).read_text()
        # SQLite exercises the INSERT/conflict behavior; PostgreSQL JSON casts
        # are the only syntax adaptation. This is not a PostgreSQL rehearsal.
        sql = sql.replace("::json", "")

        def seed_sql():
            db.connection().exec_driver_sql(sql)
            db.commit()

        return seed_sql
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr("app.db.seed_agents.SessionLocal", factory)
    return seed_agents


def test_every_seeded_agent_is_explicitly_approved() -> None:
    assert {agent["status"] for agent in INITIAL_AGENTS} == {"approved"}


def test_seeding_a_fresh_database_makes_the_agents_routable(db: Session, seed) -> None:
    seed()
    routable = {agent.id for agent in routable_agents(db)}
    assert HELLO_WORLD_ID in routable
    assert "chris" not in routable  # Chris is not seeded and never routes to himself


def test_neither_seed_path_inserts_chris(db: Session, seed) -> None:
    seed()
    assert db.get(Agent, "chris") is None
    assert {agent.id for agent in db.scalars(select(Agent))} == {
        agent["id"] for agent in INITIAL_AGENTS
    }


def test_reseeding_keeps_a_revoked_agent_unroutable(db: Session, seed) -> None:
    seed()
    hello = db.get(Agent, HELLO_WORLD_ID)
    hello.status, hello.is_active = "revoked", False
    db.commit()

    seed()  # Neither the review decision nor the activity setting may change.

    db.refresh(hello)
    assert hello.status == "revoked"
    assert hello.is_active is False
    assert hello.id not in {agent.id for agent in routable_agents(db)}


def test_reseeding_does_not_duplicate_agents(db: Session, seed) -> None:
    seed()
    seed()
    assert len(list(db.scalars(select(Agent)))) == len(INITIAL_AGENTS)


@pytest.mark.parametrize("status", ["pending", "approved", "provisional", "revoked"])
def test_reseeding_preserves_all_existing_settings(db: Session, seed, status) -> None:
    seed()
    hello = db.get(Agent, HELLO_WORLD_ID)
    hello.status = status
    hello.is_active = False
    hello.is_featured = True
    hello.trust_tier = "privileged"
    hello.required_role = "staff"
    hello.name = "Managed agent"
    hello.description = "Managed description"
    hello.endpoint_url = "https://example.org/rpc"
    hello.card_url = "https://example.org/agent.json"
    hello.skills = [{"id": "managed"}]
    hello.capabilities = {"streaming": False}
    hello.submitted_by = "submitter@example.test"
    hello.reviewed_by = "reviewer@example.test"
    hello.reviewed_at = 123
    hello.review_note = "Keep these settings"
    hello.created_at = 100
    hello.updated_at = 200
    db.commit()
    before = {
        column.name: getattr(hello, column.name) for column in Agent.__table__.columns
    }

    # Also prove that skipping an existing record does not prevent missing seeds.
    db.delete(db.get(Agent, OSU_ID))
    db.commit()
    seed()
    db.refresh(hello)

    assert {
        column.name: getattr(hello, column.name) for column in Agent.__table__.columns
    } == before
    assert db.get(Agent, OSU_ID) is not None
    assert len(list(db.scalars(select(Agent)))) == len(INITIAL_AGENTS)
