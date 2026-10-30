"""Unit and integration tests for authentication, SSO, and permission tiers."""

import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.config import AuthConfig
from app.auth.verifier import create_session_token, create_state_token, verify_state_token
from app.chris.agent_selection import Selection
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Agent, Chat, Message, User


@pytest.fixture
def test_db():
    """Create isolated in-memory SQLite database for auth tests."""
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


def test_state_token_generation_and_verification():
    """Verify anti-CSRF state tokens sign, expire, and check purpose."""
    state = create_state_token(user_id="beav123", purpose="login")
    payload = verify_state_token(state, expected_purpose="login")
    assert payload is not None
    assert payload.get("user_id") == "beav123"
    assert payload.get("purpose") == "login"

    # Mismatched purpose should fail
    assert verify_state_token(state, expected_purpose="stepup") is None


def test_dev_login_provisions_user(test_db: Session):
    """Verify POST /auth/dev/login creates user record and returns JWT."""
    client = TestClient(app)
    response = client.post(
        "/auth/dev/login",
        json={
            "email": "test.student@oregonstate.edu",
            "display_name": "Test Student",
            "role": "student",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "test.student@oregonstate.edu"
    assert data["user"]["id"] == "test.student"
    assert data["user"]["trust_tier"] == "authenticated"

    # Verify user exists in database
    db_user = test_db.get(User, "test.student")
    assert db_user is not None
    assert db_user.email == "test.student@oregonstate.edu"


def test_get_current_user_profile(test_db: Session):
    """Verify GET /auth/me returns current user profile with valid Bearer token."""
    client = TestClient(app)
    # Login first
    login_resp = client.post(
        "/auth/dev/login",
        json={"email": "prof.beav@oregonstate.edu", "role": "faculty"},
    )
    token = login_resp.json()["access_token"]

    # Call /auth/me with Bearer token
    me_resp = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "prof.beav@oregonstate.edu"
    assert me_data["role"] == "faculty"
    assert me_data["trust_tier"] == "authenticated"


def test_unauthenticated_me_fails_401(test_db: Session):
    """Verify GET /auth/me without token fails with 401."""
    client = TestClient(app)
    resp = client.get("/auth/me")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json()["detail"]


def test_invalid_token_fails_401(test_db: Session):
    """Verify corrupt or expired token fails with 401."""
    client = TestClient(app)
    resp = client.get("/auth/me", headers={"Authorization": "Bearer corrupt.token.here"})
    assert resp.status_code == 401


def test_dev_elevate_sets_privileged_tier(test_db: Session):
    """Verify POST /auth/dev/elevate elevates session to privileged tier."""
    client = TestClient(app)
    login_resp = client.post("/auth/dev/login", json={"email": "beav.admin@oregonstate.edu"})
    token = login_resp.json()["access_token"]

    elevate_resp = client.post(
        "/auth/dev/elevate", headers={"Authorization": f"Bearer {token}"}
    )
    assert elevate_resp.status_code == 200
    elevated_data = elevate_resp.json()
    assert elevated_data["user"]["trust_tier"] == "privileged"
    assert elevated_data["user"]["elevated_until"] is not None

    # Check /auth/me with new token
    elevated_token = elevated_data["access_token"]
    me_resp = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {elevated_token}"}
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["trust_tier"] == "privileged"


def test_dev_bypass_header_injection(test_db: Session):
    """Verify X-Dev-User-Email header auto-authenticates without Bearer token."""
    client = TestClient(app)
    resp = client.get(
        "/auth/me", headers={"X-Dev-User-Email": "header.beav@oregonstate.edu"}
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "header.beav@oregonstate.edu"


def test_authorize_url_generation():
    """Verify GET /auth/authorize returns valid state and dev_bypass flag."""
    client = TestClient(app)
    resp = client.get("/auth/authorize")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert data["dev_bypass"] is True


@patch("app.chris.router.choose_agent", new_callable=AsyncMock)
@patch("app.chris.router.generate", new_callable=AsyncMock)
def test_authenticated_chat_persistence(mock_generate, mock_choose_agent, test_db: Session):
    """Verify chat turn with Bearer token sets user_id and session_type=authenticated."""
    mock_choose_agent.return_value = Selection(agent=None, confidence=0.0, reason="Direct")
    mock_generate.return_value = "Hello from Chris to authenticated user!"

    client = TestClient(app)
    login_resp = client.post("/auth/dev/login", json={"email": "chat.beav@oregonstate.edu"})
    token = login_resp.json()["access_token"]

    msg_resp = client.post(
        "/chris/message",
        json={"message": "Can you check my schedule?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert msg_resp.status_code == 200
    chat_id = msg_resp.json()["chat_id"]
    assert chat_id is not None

    db_chat = test_db.get(Chat, chat_id)
    assert db_chat is not None
    assert db_chat.user_id == "chat.beav"
    assert db_chat.session_type == "authenticated"
    assert db_chat.expires_at is None  # Authenticated chats do not expire after 2h


@patch("app.chris.router.choose_agent", new_callable=AsyncMock)
@patch("app.chris.router.generate", new_callable=AsyncMock)
def test_idor_protection_with_auth_tokens(mock_generate, mock_choose_agent, test_db: Session):
    """Verify user cannot append messages to another user's authenticated chat."""
    mock_choose_agent.return_value = Selection(agent=None, confidence=0.0, reason="Direct")
    mock_generate.return_value = "Response"

    client = TestClient(app)
    # User 1 creates a chat
    u1_login = client.post("/auth/dev/login", json={"email": "user1@oregonstate.edu"})
    u1_token = u1_login.json()["access_token"]
    u1_resp = client.post(
        "/chris/message",
        json={"message": "User 1 confidential chat"},
        headers={"Authorization": f"Bearer {u1_token}"},
    )
    chat_id = u1_resp.json()["chat_id"]

    # User 2 logs in
    u2_login = client.post("/auth/dev/login", json={"email": "user2@oregonstate.edu"})
    u2_token = u2_login.json()["access_token"]

    # User 2 attempts to send a turn to User 1's chat
    u2_hijack = client.post(
        "/chris/message",
        json={"message": "Attempted turn injection", "chat_id": chat_id},
        headers={"Authorization": f"Bearer {u2_token}"},
    )
    assert u2_hijack.status_code == 403
    assert "Access denied" in u2_hijack.json()["detail"]

