"""Shared fixtures for the agent registry tests.

Each test gets a fresh database (in-memory SQLite, or PostgreSQL when
``tests/databases.py`` is given one) and a client of the registry service whose card
fetcher is replaced by a fake, so no test fetches a card from the network or uses
real DNS.
"""

import logging
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from agent_registry.a2a_app import create_standalone_app
from agent_registry.cards import AgentCard, CardError
from agent_registry.db.base import RegistryBase
from agent_registry.db.session import get_db
from agent_registry.router import get_card_fetcher
from tests.databases import registry_engine


@pytest.fixture(autouse=True)
def app_loggers_enabled() -> None:
    """Keep ``agent_registry.*`` loggers on for every test.

    The migration tests run Alembic, whose ``fileConfig`` disables every logger that
    already exists. Without this, a log assertion passes or fails depending on test
    order (and "this text is not in the log" passes vacuously).
    """
    for name, logger in logging.Logger.manager.loggerDict.items():
        if name.startswith("agent_registry.") and isinstance(logger, logging.Logger):
            logger.disabled = False


ADMIN_EMAIL = "admin@example.test"
USER_EMAIL = "alice@example.test"
OTHER_EMAIL = "bob@example.test"


def make_card(
    name: str = "Math Test Agent",
    url: str = "https://math.example.test",
    description: str = "Solves arithmetic.",
    flags: list[str] | None = None,
) -> AgentCard:
    """Build a valid card for a host, the way the real fetcher would."""
    return AgentCard(
        name=name,
        description=description,
        card_url=f"{url}/.well-known/agent.json",
        endpoint_url=f"{url}/",
        skills=[{"id": "arithmetic", "name": "Arithmetic", "tags": ["math"]}],
        capabilities={"streaming": False},
        flags=flags or [],
    )


class FakeFetcher:
    """Stands in for the card fetcher: returns a canned card or raises."""

    def __init__(self) -> None:
        self.cards: dict[str, AgentCard | Exception] = {}
        self.calls: list[str] = []

    def add(self, url: str, result: AgentCard | Exception) -> None:
        """Register what fetching ``url`` should produce."""
        self.cards[url] = result

    def __call__(self, url: str) -> AgentCard:
        self.calls.append(url)
        result = self.cards.get(url)
        if result is None:
            raise CardError("The agent card request returned HTTP 404.")
        if isinstance(result, Exception):
            raise result
        return result


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


@pytest.fixture
def fetcher() -> FakeFetcher:
    """The fake card fetcher the API uses in tests."""
    fake = FakeFetcher()
    fake.add("https://math.example.test", make_card())
    return fake


@pytest.fixture
def client(
    db: Session, fetcher: FakeFetcher, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A client of the registry service, with dev authentication on and the fake fetcher."""
    monkeypatch.setenv("REGISTRY_DEV_AUTH", "true")
    monkeypatch.setenv("REGISTRY_ADMIN_EMAILS", ADMIN_EMAIL)
    # The default is auto approval; most tests exercise the manual review flow, so
    # they opt in to it here. test_approval_mode.py covers the default and auto.
    monkeypatch.setenv("REGISTRY_APPROVAL_MODE", "manual")

    def override_get_db() -> Iterator[Session]:
        yield db

    registry = create_standalone_app(
        session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    )
    registry.dependency_overrides[get_db] = override_get_db
    registry.dependency_overrides[get_card_fetcher] = lambda: fetcher
    yield TestClient(registry)


def as_user(email: str = USER_EMAIL) -> dict[str, str]:
    """Headers for the development authentication seam."""
    return {"X-User-Id": email.split("@")[0], "X-User-Email": email}


@pytest.fixture
def submit(client: TestClient) -> Callable[..., dict]:
    """Submit an agent as a user and return the created entry."""

    def _submit(url: str = "https://math.example.test", email: str = USER_EMAIL):
        response = client.post(
            "/registry/agents", json={"url": url}, headers=as_user(email)
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _submit
