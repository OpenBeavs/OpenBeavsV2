"""Shared fixtures for the agent registry tests.

Each test gets a fresh in-memory SQLite database and a FastAPI client whose card
fetcher is replaced by a fake, so no test touches the network or real DNS.
"""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.registry.cards import AgentCard, CardError
from app.registry.router import get_card_fetcher

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
    """A fresh in-memory database with every table created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


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
    """An API client with dev authentication on and the fake fetcher installed."""
    monkeypatch.setenv("REGISTRY_DEV_AUTH", "true")
    monkeypatch.setenv("REGISTRY_ADMIN_EMAILS", ADMIN_EMAIL)

    def override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_card_fetcher] = lambda: fetcher
    yield TestClient(app)
    app.dependency_overrides.clear()


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
