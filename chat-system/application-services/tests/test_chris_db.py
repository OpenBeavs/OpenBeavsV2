"""The chat API answers without storing conversations.

The tests that run the real Conversation Agent behind this API are end-to-end tests,
kept with the tests that cross systems.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from application_services.chat.a2a_client import ChrisReply, ChrisUnavailable
from application_services.config import ConfigError
from application_services.database.base import ChatSystemBase
from application_services.database.session import get_db
from application_services.main import app
from application_services.models import Chat, Message, User
from tests.databases import chat_system_engine


@pytest.fixture
def test_db():
    """Create a database for testing Chris router (in-memory SQLite by default)."""
    engine = chat_system_engine()
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )
    session = TestingSessionLocal()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield session
    app.dependency_overrides.clear()
    session.close()
    ChatSystemBase.metadata.drop_all(bind=engine)


@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
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


def test_registry_admin_api_is_not_served_here():
    """The registry serves its own admin API from its own process."""
    client = TestClient(app)
    assert client.get("/registry/agents").status_code == 404
    assert client.post("/registry/agents", json={"url": "https://x.test"}).status_code == 404


def test_chris_a2a_endpoint_is_not_served_here():
    """Chris runs only as its own process; chat reaches it over the network."""
    with TestClient(app) as client:
        card = client.get("/chris/a2a/.well-known/agent-card.json")
        rpc = client.post("/chris/a2a/", json={})
    assert card.status_code == 404
    assert rpc.status_code == 404


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
        patch("application_services.chat.service.send_message", new_callable=AsyncMock) as generate,
    ):
        generate.side_effect = error
        response = TestClient(app).post("/chat/message", json={"message": "Hello"})

    assert response.status_code == expected_status
    assert response.json() == {"detail": detail}
    assert test_db.query(Chat).count() == 0
    assert test_db.query(Message).count() == 0


def test_chat_rejects_blank_message_before_calling_chris(test_db):
    """The extracted chat handler retains validation before A2A invocation."""
    with patch("application_services.chat.service.send_message", new_callable=AsyncMock) as answer:
        response = TestClient(app).post("/chat/message", json={"message": "  "})
    assert response.status_code == 400
    assert response.json() == {"detail": "Message cannot be empty."}
    answer.assert_not_awaited()
    assert test_db.query(Message).count() == 0


@pytest.mark.parametrize("stored_type", ["guest", "authenticated"])
@pytest.mark.parametrize("claimed_user", [None, "alice", "unknown"])
@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
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


@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
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
