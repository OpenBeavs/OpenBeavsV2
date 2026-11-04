"""Integration tests for direct answers, directory filtering, and chat persistence."""

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.chat.a2a_client import ChrisUnavailable
from app.chat.service import list_active_agents, purge_expired_chats
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
def test_chris_a2a_answer_persists_chat_and_messages(mock_send, test_db: Session):
    """Verify that an A2A answer from Chris creates chat and message records."""
    mock_send.return_value = "Hello! I am Chris, how can I help you today?"
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
    chat_id = data["chat_id"]
    assert chat_id is not None

    # Verify database persistence
    chat = test_db.get(Chat, chat_id)
    assert chat is not None
    assert chat.guest_session_id == "iframe_guest_123"
    assert chat.source_domain == "library.oregonstate.edu"
    assert chat.session_type == "guest"
    assert chat.expires_at is not None  # Has 2-hour TTL

    # Verify messages with explicit ascending order
    messages = (
        test_db.query(Message)
        .filter(Message.chat_id == chat_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    assert len(messages) == 2
    assert messages[0].sender_type == "user"
    assert messages[0].content == "Hi Chris!"
    assert messages[1].sender_type == "agent"
    assert messages[1].content == "Hello! I am Chris, how can I help you today?"
    assert messages[0].created_at < messages[1].created_at


def test_health_check_endpoint():
    """Verify GET /health returns 200 OK status."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "OpenBeavs v2"}


def test_frontend_chat_uses_real_adk_chris(test_db, monkeypatch):
    """The frontend API calls the real A2A agent and persists its response."""
    selection = AsyncMock(return_value='{"agent":"none"}')
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
    assert test_db.get(Chat, data["chat_id"]).guest_session_id == "test-guest"
    messages = test_db.query(Message).order_by(Message.created_at).all()
    assert [message.content for message in messages] == [
        "Hello Chris",
        "Gemini answer.",
    ]


def test_unavailable_registry_gemini_reply_is_saved_as_a_chat_turn(
    test_db, monkeypatch
):
    """A missing registry uses Gemini's answer, which chat persists normally."""
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
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(unavailable)),
    )
    with TestClient(app) as client:
        response = client.post("/chat/message", json={"message": "Hello"})
    assert response.status_code == 200
    assert response.json()["response"] == "Gemini answer."
    answer.assert_awaited_once_with("Hello", [])
    assert test_db.query(Chat).count() == 1
    messages = test_db.query(Message).order_by(Message.created_at).all()
    assert [message.content for message in messages] == [
        "Hello",
        "Gemini answer.",
    ]


@pytest.mark.parametrize(
    ("error", "expected_status", "detail"),
    [
        (
            ConfigError("Missing Chris endpoint configuration"),
            500,
            "Missing Chris endpoint configuration",
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


@patch("app.chat.service.send_message", new_callable=AsyncMock)
def test_persist_turn_db_failure_still_returns_reply(mock_send, test_db: Session):
    """Verify that a database error during persistence does not 500, but returns the reply with chat_id=None."""
    mock_send.return_value = "Reply from Chris despite DB error"
    client = TestClient(app)

    # Force a database failure during _persist_turn
    with patch("app.chat.service._persist_turn", return_value=None):
        payload = {"message": "Hello Chris"}
        response = client.post("/chat/message", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["response"] == "Reply from Chris despite DB error"
        assert data["chat_id"] is None


@patch("app.chat.service.send_message", new_callable=AsyncMock)
def test_history_loaded_from_db_when_chat_id_provided(mock_send, test_db: Session):
    """Verify that when chat_id is provided, messages are loaded from the DB rather than form.history."""
    mock_send.return_value = "Second turn response"
    client = TestClient(app)

    # 1. Create existing chat with 2 stored turns
    chat = Chat(id="chat-12345", session_type="guest")
    test_db.add(chat)
    test_db.commit()

    now_ms = int(time.time() * 1000)
    m1 = Message(
        chat_id="chat-12345",
        sender_type="user",
        content="First question",
        created_at=now_ms,
    )
    m2 = Message(
        chat_id="chat-12345",
        sender_type="agent",
        content="First answer",
        created_at=now_ms + 1,
    )
    test_db.add_all([m1, m2])
    test_db.commit()

    # 2. Client sends chat_id and spoofed/divergent client history
    payload = {
        "chat_id": "chat-12345",
        "message": "Second question",
        "history": [{"role": "user", "content": "Spoofed message not in DB"}],
    }
    response = client.post("/chat/message", json=payload)
    assert response.status_code == 200

    # Verify that A2A was called with DB messages, not the spoofed history
    call_args = mock_send.call_args.args[1]
    message_contents = [m["content"] for m in call_args]
    assert "First question" in message_contents
    assert "First answer" in message_contents
    assert "Spoofed message not in DB" not in message_contents


@patch("app.chat.service.send_message", new_callable=AsyncMock)
def test_authenticated_user_vs_unverified_guest(mock_send, test_db: Session):
    """Verify that only users existing in the database are authenticated without TTL; unverified user_ids remain guest with TTL."""
    mock_send.return_value = "Hello"
    client = TestClient(app)

    # 1. Real user in DB
    user = User(
        id="real-student",
        email="real@oregonstate.edu",
        display_name="Real Student",
        role="student",
    )
    test_db.add(user)
    test_db.commit()

    # Chat with verified user_id
    res1 = client.post(
        "/chat/message",
        json={"message": "Hi", "user_id": "real-student"},
    )
    assert res1.status_code == 200
    chat1 = test_db.get(Chat, res1.json()["chat_id"])
    assert chat1.session_type == "authenticated"
    assert chat1.user_id == "real-student"
    assert chat1.expires_at is None

    # Chat with unverified user_id
    res2 = client.post(
        "/chat/message",
        json={"message": "Hi", "user_id": "fake-student-id"},
    )
    assert res2.status_code == 200
    chat2 = test_db.get(Chat, res2.json()["chat_id"])
    assert chat2.session_type == "guest"
    assert chat2.user_id is None
    assert chat2.expires_at is not None


def test_purge_expired_chats(test_db: Session):
    """Verify that expired guest chats are purged and active ones are retained."""
    now = int(time.time())

    # Expired chat
    expired_chat = Chat(
        id="expired-1",
        session_type="guest",
        expires_at=now - 100,
    )
    # Active guest chat
    active_chat = Chat(
        id="active-1",
        session_type="guest",
        expires_at=now + 3600,
    )
    # Authenticated chat (no expires_at)
    auth_chat = Chat(
        id="auth-1",
        session_type="authenticated",
        expires_at=None,
    )
    test_db.add_all([expired_chat, active_chat, auth_chat])
    test_db.commit()

    client = TestClient(app)
    response = client.delete("/chat/chats/expired")
    assert response.status_code == 200
    assert response.json() == {"purged": 1}

    assert test_db.get(Chat, "expired-1") is None
    assert test_db.get(Chat, "active-1") is not None
    assert test_db.get(Chat, "auth-1") is not None

    # Also test the direct python purge function
    assert purge_expired_chats(test_db) == 0


def test_idor_prevention_on_chat_access(test_db: Session):
    """Verify that accessing another user's or guest's chat returns 403 Forbidden."""
    client = TestClient(app)

    # 1. Create a chat owned by user 'alice'
    alice = User(
        id="alice",
        email="alice@oregonstate.edu",
        display_name="Alice",
        role="student",
    )
    test_db.add(alice)
    alice_chat = Chat(
        id="alice-secret-chat", user_id="alice", session_type="authenticated"
    )
    test_db.add(alice_chat)

    # 2. Create a guest chat with token 'guest_token_123'
    guest_chat = Chat(
        id="guest-chat-1",
        guest_session_id="guest_token_123",
        session_type="guest",
    )
    test_db.add(guest_chat)
    test_db.commit()

    # Bob tries to access Alice's chat -> 403
    bob = User(
        id="bob", email="bob@oregonstate.edu", display_name="Bob", role="student"
    )
    test_db.add(bob)
    test_db.commit()

    res1 = client.post(
        "/chat/message",
        json={
            "message": "Can I read Alice's chat?",
            "chat_id": "alice-secret-chat",
            "user_id": "bob",
        },
    )
    assert res1.status_code == 403

    # An anonymous caller tries to access guest chat with wrong token -> 403
    res2 = client.post(
        "/chat/message",
        json={
            "message": "Can I append to guest chat?",
            "chat_id": "guest-chat-1",
            "guest_session_id": "wrong_guest_token",
        },
    )
    assert res2.status_code == 403
