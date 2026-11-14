"""A real Chat + Chris + registry pipeline in one process, with a fake model.

What is real: the Chat router and service, Chris's ADK agent served over A2A, Chris's
registry client, the registry's A2A application (card, executor, selection, limiter,
eligibility checks) and its database queries. All three speak the real A2A protocol
through the official SDK over in-memory HTTP.

What is fake: the Gemini call inside the registry (``call_llm``), because tests must be
deterministic and free. Nothing here proves how a real model behaves, that a Google
token is accepted (the registry runs in its local-development mode, no token is sent),
or that anything works when deployed. Tests enable dispatch explicitly and mock
the expert's HTTP responses; the fixture defaults to selection-only diagnostics.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.chat import a2a_client
from app.chris import registry_client
from app.db.base import Base
from app.db.session import get_db
from app.main import app as backend_app
from app.models import Agent
from app.registry.a2a import MOUNT_PATH
from app.registry.a2a_app import create_registry_a2a_app
from app.registry.a2a_auth import open_verifier
from app.registry.llm import ModelLimiter

REGISTRY_ORIGIN = "http://registry.test"
CHRIS_ORIGIN = "http://testserver"

FakeModel = Callable[[str, str, dict], Awaitable[str]]


def reply(agent_id: str, confidence: float = 0.95, reason: str = "It fits.") -> str:
    """The JSON text a well-behaved model returns."""
    return json.dumps(
        {"agent_id": agent_id, "confidence": confidence, "reason": reason}
    )


class SlowRegistryTransport(httpx.AsyncBaseTransport):
    """Delays the registry's *message* reply (not card discovery) by ``state.delay``.

    This models "the registry is slow to answer" as Chris experiences it. A slow model
    inside an in-memory ASGI app cannot be cancelled cleanly by the caller's deadline
    (an artifact of in-memory transport; a real server just finishes and discards), so
    the delay is injected here, where cancellation is well defined. The real-socket
    behavior is checked separately in the live-stack tests.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, state: "Pipeline") -> None:
        self.inner = inner
        self.state = state

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and self.state.registry_delay:
            await asyncio.sleep(self.state.registry_delay)
        return await self.inner.handle_async_request(request)


class Pipeline:
    """Handles to the running pieces, plus a record of what the registry was asked."""

    def __init__(self, client: TestClient, factory: sessionmaker) -> None:
        self.client = client
        self.factory = factory
        self.model: FakeModel = self._default_model
        self.prompts: list[tuple[str, str]] = []  # (system, user) per model call
        self.limiter: ModelLimiter | None = None
        self.registry_delay: float = 0.0

    async def _default_model(self, system: str, user: str, schema: dict) -> str:
        return reply("none", 0.9, "Nothing fits.")

    def set_model(self, fn: FakeModel) -> None:
        self.model = fn

    def choose(self, *args, **kwargs) -> None:
        """Use a constant fake decision while retaining the normal prompt recording."""

        async def model(system, user, schema):
            return reply(*args, **kwargs)

        self.set_model(model)

    async def _recording_model(self, system: str, user: str, schema: dict) -> str:
        self.prompts.append((system, user))
        return await self.model(system, user, schema)

    def ask(self, message: str, **fields) -> httpx.Response:
        """What the frontend does: POST /chat/message."""
        return self.client.post("/chat/message", json={"message": message, **fields})

    def add_agent(self, agent_id: str, **overrides) -> None:
        with self.factory() as db:
            db.add(
                Agent(
                    **{
                        "id": agent_id,
                        "name": agent_id.replace("-", " ").title(),
                        "description": f"The {agent_id} expert.",
                        "endpoint_url": f"https://{agent_id}.example.test/rpc",
                        "card_url": f"https://{agent_id}.example.test/card.json",
                        "trust_tier": "public",
                        "skills": [{"name": agent_id, "tags": [agent_id]}],
                        "is_active": True,
                        "status": "approved",
                        **overrides,
                    }
                )
            )
            db.commit()

    def update_agent(self, agent_id: str, **fields) -> None:
        with self.factory() as db:
            agent = db.get(Agent, agent_id)
            for name, value in fields.items():
                setattr(agent, name, value)
            db.commit()


@pytest.fixture
def pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Pipeline]:
    """Chat -> Chris -> registry, wired in memory, over one SQLite file."""
    for name in (
        "REGISTRY_A2A_AUTH",
        "REGISTRY_MODEL_TIMEOUT_SECONDS",
        "REGISTRY_MODEL_QUEUE_SECONDS",
        "REGISTRY_MODEL_MAX_CONCURRENCY",
        "K_SERVICE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHRIS_PUBLIC_URL", CHRIS_ORIGIN)
    monkeypatch.setenv("CHRIS_A2A_URL", f"{CHRIS_ORIGIN}/chris/a2a/")
    monkeypatch.setenv("REGISTRY_A2A_URL", f"{REGISTRY_ORIGIN}{MOUNT_PATH}")
    monkeypatch.setenv("CHRIS_SELECTION_ONLY", "true")
    monkeypatch.setenv("REGISTRY_A2A_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("CHRIS_A2A_TIMEOUT_SECONDS", "10")

    engine = create_engine(
        f"sqlite:///{tmp_path / 'pipeline.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    state: dict[str, Pipeline] = {}

    async def model(system: str, user: str, schema: dict) -> str:
        return await state["p"]._recording_model(system, user, schema)

    registry_root = FastAPI()
    registry_root.mount(
        MOUNT_PATH,
        create_registry_a2a_app(
            base_url=REGISTRY_ORIGIN,
            verifier=open_verifier,
            session_factory=factory,
            call_llm=model,
            limiter=ModelLimiter(4, 1),
        ),
    )

    backend_app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        registry_client,
        "_http_client",
        lambda timeout: httpx.AsyncClient(
            transport=SlowRegistryTransport(
                httpx.ASGITransport(app=registry_root), state["p"]
            ),
            timeout=timeout,
        ),
    )
    monkeypatch.setattr(
        a2a_client,
        "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=backend_app)),
    )
    with TestClient(backend_app) as client:
        p = Pipeline(client, factory)
        state["p"] = p
        yield p
    backend_app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def experts(pipeline: Pipeline) -> Pipeline:
    """Two eligible experts, plus ones that must never be offered."""
    pipeline.add_agent("osu-expert", description="Oregon State University questions.")
    pipeline.add_agent("math-expert", description="Arithmetic and percentages.")
    pipeline.add_agent("revoked-expert", status="revoked", is_active=False)
    return pipeline


def slow(seconds: float, then: str) -> FakeModel:
    """A fake model that takes ``seconds`` before answering."""

    async def model(system: str, user: str, schema: dict) -> str:
        await asyncio.sleep(seconds)
        return then

    return model
