"""Unit tests for the agent registry's SQLAlchemy model."""

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from agent_registry.models import Agent


def test_registry_tables_stand_alone(db: Session) -> None:
    """The registry's table is created without the chat system's, and points at none."""
    inspector = inspect(db.get_bind())
    assert inspector.get_table_names() == ["agents"]
    assert inspector.get_foreign_keys("agents") == []


def test_create_agent(db: Session) -> None:
    """Test creating an A2A agent record."""
    agent = Agent(
        id="honors-college",
        name="Honors College Agent",
        description="Answers questions about OSU Honors College",
        endpoint_url="https://agents.oregonstate.edu/honors/message/send",
        card_url="https://agents.oregonstate.edu/honors/.well-known/agent.json",
        trust_tier="public",
        skills=["honors thesis", "scholarships", "advising"],
        capabilities={"streaming": True},
    )
    db.add(agent)
    db.commit()

    saved = db.get(Agent, "honors-college")
    assert saved is not None
    assert saved.name == "Honors College Agent"
    assert saved.trust_tier == "public"
    assert "honors thesis" in saved.skills
    assert saved.is_active is True
