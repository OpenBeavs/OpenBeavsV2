"""Chris's discovery card comes from his own code, not from the registry's table.

Chris is the orchestrator, not a registered agent: the registry holds no row for him,
and his card is still served. This exercises the registry's model and Chris together.
"""

from collections.abc import Iterator

import pytest
from agent_registry.db.base import RegistryBase
from agent_registry.models import Agent
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from tests.databases import registry_engine


@pytest.fixture
def db() -> Iterator[Session]:
    """A fresh database holding the registry's tables and no others."""
    engine = registry_engine()
    session = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )()
    yield session
    session.close()
    RegistryBase.metadata.drop_all(bind=engine)


class TestChrisIsStillAvailableButNotRegistered:
    def test_discovery_card_is_served_by_code_without_a_database_row(
        self, db: Session
    ) -> None:
        from conversation_agent.run import create_app

        assert db.get(Agent, "chris") is None
        with TestClient(create_app()) as client:
            response = client.get("/chris/a2a/.well-known/agent-card.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "chris"
        assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
        assert card["skills"]
