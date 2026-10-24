"""Seeding the production agents must not undo an admin's review decisions."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.seed_agents import INITIAL_AGENTS, seed_agents
from app.models import Agent
from app.registry.service import routable_agents

HELLO_WORLD_ID = "26b643fd-9a61-465d-b075-89ba84d503cb"


@pytest.fixture
def seed(db: Session, monkeypatch: pytest.MonkeyPatch):
    """Run ``seed_agents`` against the test database."""
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr("app.db.seed_agents.SessionLocal", factory)
    return seed_agents


def test_every_seeded_agent_is_explicitly_approved() -> None:
    assert {agent["status"] for agent in INITIAL_AGENTS} == {"approved"}


def test_seeding_a_fresh_database_makes_the_agents_routable(db: Session, seed) -> None:
    seed()
    routable = {agent.id for agent in routable_agents(db)}
    assert HELLO_WORLD_ID in routable
    assert "chris" not in routable  # Chris never routes to himself


def test_reseeding_keeps_a_revoked_agent_unroutable(db: Session, seed) -> None:
    seed()
    hello = db.get(Agent, HELLO_WORLD_ID)
    hello.status, hello.is_active = "revoked", False
    db.commit()

    seed()  # the seed sets is_active again, but must leave the review status alone

    db.refresh(hello)
    assert hello.status == "revoked"
    assert hello.id not in {agent.id for agent in routable_agents(db)}


def test_reseeding_does_not_duplicate_agents(db: Session, seed) -> None:
    seed()
    seed()
    assert len(list(db.scalars(select(Agent)))) == len(INITIAL_AGENTS)
