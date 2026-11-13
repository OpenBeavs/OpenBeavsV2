"""Integration tests for direct answers, directory filtering, and chat persistence."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.chat.a2a_client import ChrisReply, ChrisUnavailable
from app.chat.service import list_active_agents
from app.chris.routing import RoutingResult
from app.config import ConfigError
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Agent, Chat, Message, User


@pytest.fixture
def test_db():
    """Create in-memory SQLite database for testing Chris router."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )
    session = TestingSessionLocal()

    # Seed an agent
    agent = Agent(
        id="osu-rag-agent",
        name="OSU Expert (RAG)",
        description="Expert on Oregon State University academics and campus life.",
        endpoint_url="https://example.com/a2a",
        skills=["osu", "admissions", "campus"],
        trust_tier="public",
        is_active=True,
        status="approved",  # new agents default to "pending", which Chris never routes to
    )
    session.add(agent)
    session.commit()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield session
    app.dependency_overrides.clear()
    session.close()
    Base.metadata.drop_all(bind=engine)


@patch("app.chat.service.send_message", new_callable=AsyncMock)
def test_guest_answer_does_not_persist(mock_send, test_db: Session):
    """Guest answers must not create chat or message records."""
    mock_send.return_value = ChrisReply("Hello! I am Chris, how can I help you today?")
    client = TestClient(app)

    payload = {
        "message": "Hi Chris!",
        "guest_session_id": "iframe_guest_123",
        "source_domain": "library.oregonstate.edu",
    }
    response = client.post("/chat/message", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Hello! I am Chris, how can I help you today?"
    assert data["routed_to"] is None
    assert data["routing_confidence"] is None
    assert data["chat_id"] is None
    assert test_db.query(Chat).count() == 0
    assert test_db.query(Message).count() == 0


def test_health_check_endpoint():
    """Verify GET /health returns 200 OK status."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "OpenBeavs v2"}


def test_frontend_chat_uses_real_adk_chris(test_db, monkeypatch):
    """The frontend API calls the real A2A agent without storing its response."""
    selection = AsyncMock(return_value=RoutingResult(status="no_match"))
    monkeypatch.setattr("app.chris.registry_client.select_agent", selection)
    answer = AsyncMock(return_value="Gemini answer.")
    monkeypatch.setattr("app.chris.gemini.answer", answer)
    history = [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
    ]
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")
    monkeypatch.setenv("CHRIS_PUBLIC_URL", "http://testserver")
    requests = []

    def http_client():
        async def record(request):
            requests.append(request)

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            event_hooks={"request": [record]},
        )

    with (
        TestClient(app) as client,
        patch("app.chat.a2a_client._http_client", side_effect=http_client),
    ):
        response = client.post(
            "/chat/message",
            json={
                "message": "Hello Chris",
                "guest_session_id": "test-guest",
                "history": history,
            },
        )
        assert (
            client.post("/chris/message", json={"message": "Hello"}).status_code == 404
        )
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Gemini answer."
    selection.assert_awaited_once_with("Hello Chris", history)
    answer.assert_awaited_once_with("Hello Chris", history)
    assert data["routed_to"] is None
    assert [request.url.path for request in requests] == ["/chris/a2a/"]
    assert data["chat_id"] is None
    assert test_db.query(Chat).count() == 0
    assert test_db.query(Message).count() == 0


def test_unavailable_registry_gemini_reply_is_not_saved(
    test_db, monkeypatch
):
    """A missing registry uses Gemini's answer without storing a turn."""
    answer = AsyncMock(return_value="Gemini answer.")
    monkeypatch.setattr("app.chris.gemini.answer", answer)
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")
    monkeypatch.setenv("REGISTRY_A2A_URL", "http://registry.example.test/")
    monkeypatch.setattr(
        "app.chat.a2a_client._http_client",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )

    def unavailable(request):
        raise httpx.ConnectError("Registry is not running", request=request)

    monkeypatch.setattr(
        "app.chris.registry_client._http_client",
        lambda timeout: httpx.AsyncClient(
            transport=httpx.MockTransport(unavailable)
        ),
    )
    with TestClient(app) as client:
        response = client.post("/chat/message", json={"message": "Hello"})
    assert response.status_code == 200
    assert response.json()["response"] == "Gemini answer."
    answer.assert_awaited_once_with("Hello", [])
    assert response.json()["chat_id"] is None
    assert test_db.query(Chat).count() == 0
    assert test_db.query(Message).count() == 0


@pytest.mark.parametrize(
    ("error", "expected_status", "detail"),
    [
        (
            ConfigError("Missing Chris endpoint configuration"),
            500,
            "Chris is temporarily unavailable. Please try again shortly.",
        ),
        (
            ChrisUnavailable("Chris unavailable"),
            503,
            "Chris is temporarily unavailable. Please try again shortly.",
        ),
    ],
)
def test_chat_preserves_chris_error_responses(test_db, error, expected_status, detail):
    """Moving the HTTP layer preserves errors and avoids saving failed turns."""
    with (
        patch("app.chat.service.send_message", new_callable=AsyncMock) as generate,
    ):
        generate.side_effect = error
        response = TestClient(app).post("/chat/message", json={"message": "Hello"})

    assert response.status_code == expected_status
    assert response.json() == {"detail": detail}
    assert test_db.query(Chat).count() == 0
    assert test_db.query(Message).count() == 0


def test_chat_rejects_blank_message_before_calling_chris(test_db):
    """The extracted chat handler retains validation before A2A invocation."""
    with patch("app.chat.service.send_message", new_callable=AsyncMock) as answer:
        response = TestClient(app).post("/chat/message", json={"message": "  "})
    assert response.status_code == 400
    assert response.json() == {"detail": "Message cannot be empty."}
    answer.assert_not_awaited()
    assert test_db.query(Message).count() == 0


def test_list_agents_endpoint(test_db: Session):
    """Verify GET /chat/agents returns active registered agents."""
    client = TestClient(app)
    response = client.get("/chat/agents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["id"] == "osu-rag-agent"
    assert data[0]["name"] == "OSU Expert (RAG)"
    assert data[0]["endpoint_url"] == "https://example.com/a2a"


def test_installed_agents_empty_returns_empty_list(test_db: Session):
    """Verify that an empty agents table returns [] without inventing agent metadata."""
    test_db.query(Agent).delete()
    test_db.commit()

    with patch.dict("os.environ", {}, clear=True):
        agents = list_active_agents(test_db)
        assert agents == []


def test_installed_agents_filters_by_trust_tier_and_role(test_db: Session):
    """Verify that privileged agents or agents requiring specific roles are filtered out."""
    # Add a privileged agent
    priv_agent = Agent(
        id="internal-admin-agent",
        name="Admin Agent",
        endpoint_url="https://example.com/admin",
        trust_tier="privileged",
        is_active=True,
        status="approved",
    )
    # Add an agent requiring a specific role
    faculty_agent = Agent(
        id="grading-agent",
        name="Faculty Grading Agent",
        endpoint_url="https://example.com/grading",
        trust_tier="public",
        required_role="faculty",
        is_active=True,
        status="approved",
    )
    test_db.add_all([priv_agent, faculty_agent])
    test_db.commit()

    agents = list_active_agents(test_db)
    agent_ids = [a["id"] for a in agents]
    assert "osu-rag-agent" in agent_ids
    assert "internal-admin-agent" not in agent_ids
    assert "grading-agent" not in agent_ids


@pytest.mark.parametrize("stored_type", ["guest", "authenticated"])
@pytest.mark.parametrize("claimed_user", [None, "alice", "unknown"])
@patch("app.chat.service.send_message", new_callable=AsyncMock)
def test_legacy_ids_cannot_read_or_write_history(
    mock_send, test_db, stored_type, claimed_user
):
    """Even a real user's ID or a matching guest token cannot enable storage."""
    test_db.add(User(id="alice", email="alice@example.test", role="student"))
    test_db.flush()
    chat = Chat(id="legacy", session_type=stored_type,
                user_id="alice" if stored_type == "authenticated" else None,
                guest_session_id="old-token")
    test_db.add(chat)
    test_db.flush()
    test_db.add(Message(chat_id="legacy", sender_type="user", content="Private history"))
    test_db.commit()
    mock_send.return_value = ChrisReply("Transient answer")
    history = [{"role": "user", "content": "Browser history"}]
    response = TestClient(app).post("/chat/message", json={
        "message": "Follow up", "history": history, "chat_id": "legacy",
        "user_id": claimed_user, "guest_session_id": "old-token",
    })
    assert response.status_code == 200
    assert response.json()["chat_id"] is None
    mock_send.assert_awaited_once_with("Follow up", history)
    assert test_db.query(Chat).count() == 1
    assert test_db.query(Message).one().content == "Private history"


@patch("app.chat.service.send_message", new_callable=AsyncMock)
def test_claimed_existing_user_cannot_create_saved_chat(mock_send, test_db):
    """A body field is not verified authentication and cannot opt into saving."""
    test_db.add(User(id="alice", email="alice@example.test", role="student"))
    test_db.commit()
    mock_send.return_value = ChrisReply("Hello")
    response = TestClient(app).post("/chat/message", json={
        "message": "Hi", "user_id": "alice",
    })
    assert response.status_code == 200
    assert response.json()["chat_id"] is None
    assert test_db.query(Chat).count() == 0
    assert test_db.query(Message).count() == 0
