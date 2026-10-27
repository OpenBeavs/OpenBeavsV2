"""Integration tests for Chris routing against the database and chat persistence."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.chris.agent_selection import Selection
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Agent, Chat, Message


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


@patch("app.chris.router.choose_agent", new_callable=AsyncMock)
@patch("app.chris.router.generate", new_callable=AsyncMock)
def test_chris_direct_answer_persists_chat_and_messages(
    mock_generate, mock_choose_agent, test_db: Session
):
    """Verify that a direct answer from Chris creates chat and message records."""
    mock_choose_agent.return_value = Selection(
        agent=None, confidence=0.0, reason="No match"
    )
    mock_generate.return_value = "Hello! I am Chris, how can I help you today?"
    client = TestClient(app)

    payload = {
        "message": "Hi Chris!",
        "guest_session_id": "iframe_guest_123",
        "source_domain": "library.oregonstate.edu",
    }
    response = client.post("/chris/message", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Hello! I am Chris, how can I help you today?"
    chat_id = data["chat_id"]
    assert chat_id is not None

    # Verify database persistence
    chat = test_db.get(Chat, chat_id)
    assert chat is not None
    assert chat.guest_session_id != "iframe_guest_123"
    assert data["guest_session_id"]
    assert chat.guest_session_id != data["guest_session_id"]
    assert chat.source_domain == "library.oregonstate.edu"
    assert chat.session_type == "guest"
    assert chat.expires_at is not None  # Has 2-hour TTL

    # Verify messages
    messages = (
        test_db.query(Message)
        .filter(Message.chat_id == chat_id)
        .order_by(Message.sequence)
        .all()
    )
    assert len(messages) == 2
    assert messages[0].sender_type == "user"
    assert messages[0].content == "Hi Chris!"
    assert messages[1].sender_type == "agent"
    assert messages[1].content == "Hello! I am Chris, how can I help you today?"


@patch("app.chris.router.choose_agent", new_callable=AsyncMock)
def test_chris_routed_agent_persists_chat_and_messages(
    mock_choose_agent, test_db: Session
):
    """Verify that routing to an agent records the agent ID in chat and messages."""
    agent = test_db.get(Agent, "osu-rag-agent")
    mock_choose_agent.return_value = Selection(
        agent=agent, confidence=0.92, reason="Query about OSU"
    )
    client = TestClient(app)

    payload = {
        "message": "Tell me about OSU admissions",
        "guest_session_id": "guest_abc",
        "source_domain": "admissions.oregonstate.edu",
    }
    response = client.post("/chris/message", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["routed_to"] == "osu-rag-agent"
    assert data["agent_name"] == "OSU Expert (RAG)"
    chat_id = data["chat_id"]
    assert chat_id is not None

    # Verify database persistence
    chat = test_db.get(Chat, chat_id)
    assert chat is not None
    assert chat.agent_id == "osu-rag-agent"

    messages = (
        test_db.query(Message)
        .filter(Message.chat_id == chat_id)
        .order_by(Message.sequence)
        .all()
    )
    assert len(messages) == 2
    assert messages[0].sender_type == "user"
    assert messages[1].sender_type == "agent"
    assert messages[1].meta["routing_confidence"] == 0.92


def test_health_check_endpoint():
    """Verify GET /health returns 200 OK status."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "OpenBeavs v2"}


def test_list_agents_endpoint(test_db: Session):
    """Verify GET /chris/agents returns active registered agents."""
    client = TestClient(app)
    response = client.get("/chris/agents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["id"] == "osu-rag-agent"
    assert data[0]["name"] == "OSU Expert (RAG)"
    assert data[0]["endpoint_url"] == "https://example.com/a2a"
