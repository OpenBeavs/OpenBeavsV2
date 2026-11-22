"""Unit and integration tests for authentication, SSO, and permission tiers."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from application_services.auth.verifier import (
    create_state_token,
    verify_state_token,
)
from application_services.chat.a2a_client import ChrisReply
from application_services.db.base import ChatSystemBase
from application_services.db.session import get_db
from application_services.main import app
from application_services.models import User
from tests.databases import chat_system_engine


@pytest.fixture(autouse=True)
def setup_auth_env(monkeypatch):
    """Enable dev bypass and mock MS auth config for auth tests by default so tests run deterministically in CI."""
    monkeypatch.setenv("AUTH_BYPASS_DEV", "true")
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "mock-client-id")
    monkeypatch.setenv("MICROSOFT_CLIENT_TENANT_ID", "mock-tenant-id")


@pytest.fixture(autouse=True)
def test_db():
    """Create an isolated database for auth tests (in-memory SQLite by default)."""
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


def test_state_token_generation_and_verification():
    """Verify anti-CSRF state tokens sign, expire, and check purpose."""
    state = create_state_token(user_id="beav123", purpose="login")
    payload = verify_state_token(state, expected_purpose="login")
    assert payload is not None
    assert payload.get("user_id") == "beav123"
    assert payload.get("purpose") == "login"

    # Mismatched purpose should fail
    assert verify_state_token(state, expected_purpose="stepup") is None


def test_dev_bypass_disabled_returns_403(monkeypatch, test_db: Session):
    """Verify POST /auth/dev/login fails with 403 when dev bypass is disabled."""
    monkeypatch.setenv("AUTH_BYPASS_DEV", "false")
    client = TestClient(app)
    response = client.post(
        "/auth/dev/login",
        json={"email": "test.student@oregonstate.edu"},
    )
    assert response.status_code == 403
    assert "Dev login is disabled in this environment" in response.json()["detail"]


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


def test_login_redirect():
    """Verify GET /auth/login returns a 307 redirect to Microsoft login."""
    client = TestClient(app)
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 307
    assert "login.microsoftonline.com" in resp.headers["location"]


def test_login_redirect_unconfigured(monkeypatch):
    """Verify GET /auth/login returns 503 if Microsoft SSO is not configured."""
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "")
    client = TestClient(app)
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 503
    assert "Microsoft SSO is not configured" in resp.json()["detail"]


@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
def test_authenticated_chat_message(mock_send, test_db: Session):
    """Verify authenticated user can interact with chat endpoint using Bearer token."""
    mock_send.return_value = ChrisReply(
        text="Hello from Chris to authenticated user!", routing=None
    )

    client = TestClient(app)
    login_resp = client.post("/auth/dev/login", json={"email": "chat.beav@oregonstate.edu"})
    token = login_resp.json()["access_token"]

    msg_resp = client.post(
        "/chat/message",
        json={"message": "Can you check my schedule?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert msg_resp.status_code == 200
    data = msg_resp.json()
    assert data["response"] == "Hello from Chris to authenticated user!"
    assert data["chat_id"] is None


def test_cookie_based_authentication(test_db: Session):
    """Verify openbeavs_token cookie authenticates GET /auth/me."""
    client = TestClient(app)
    login_resp = client.post(
        "/auth/dev/login",
        json={"email": "cookie.beav@oregonstate.edu", "display_name": "Cookie Beav", "role": "student"},
    )
    token = login_resp.json()["access_token"]

    # Send request with cookie instead of Authorization header
    client.cookies.set("openbeavs_token", token)
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "cookie.beav@oregonstate.edu"
    assert data["display_name"] == "Cookie Beav"


def test_oauth_callback_error_is_html_escaped():
    """Verify /auth/callback escapes user-controlled error parameter to prevent XSS."""
    client = TestClient(app)
    xss_payload = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
    resp = client.get("/auth/callback", params={"error": xss_payload})
    assert resp.status_code == 400
    assert "<script>" not in resp.text
    assert "<img" not in resp.text
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in resp.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in resp.text


def test_step_up_callback_error_is_html_escaped():
    """Verify /auth/step-up/callback escapes user-controlled error parameter to prevent XSS."""
    client = TestClient(app)
    xss_payload = '<script>alert("stepup-xss")</script>'
    resp = client.get("/auth/step-up/callback", params={"error": xss_payload})
    assert resp.status_code == 400
    assert "<script>" not in resp.text
    assert "&lt;script&gt;alert(&quot;stepup-xss&quot;)&lt;/script&gt;" in resp.text


def test_auth_popup_uses_configured_frontend_origin(monkeypatch):
    """Verify _auth_popup_response does not use wildcard '*' and uses the configured frontend origin."""
    from application_services.auth.router import _auth_popup_response

    monkeypatch.setenv("FRONTEND_ORIGIN", "https://openbeavs.oregonstate.edu")
    resp = _auth_popup_response("token123", {"email": "test@oregonstate.edu"})
    content = resp.body.decode()

    # Must NOT use wildcard targetOrigin
    assert 'postMessage(payload, "*")' not in content
    # Must use configured frontend origin
    assert 'postMessage(payload, "https://openbeavs.oregonstate.edu")' in content


def test_frontend_origin_derives_from_redirect_uri(monkeypatch):
    """Verify AuthConfig.frontend_origin falls back to netloc of MICROSOFT_REDIRECT_URI."""
    from application_services.auth.config import AuthConfig

    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    monkeypatch.setenv("MICROSOFT_REDIRECT_URI", "http://localhost:8080/oauth/microsoft/callback")
    assert AuthConfig.frontend_origin() == "http://localhost:8080"


def test_authorize_sets_browser_state_cookie():
    """Verify GET /auth/authorize binds state to browser via openbeavs_auth_state cookie."""
    from application_services.auth.config import STATE_COOKIE_NAME

    client = TestClient(app)
    resp = client.get("/auth/authorize")
    assert resp.status_code == 200
    state = resp.json()["state"]
    assert STATE_COOKIE_NAME in client.cookies
    assert client.cookies[STATE_COOKIE_NAME] == state


def test_login_redirect_sets_browser_state_cookie():
    """Verify GET /auth/login binds state to browser via openbeavs_auth_state cookie."""
    from application_services.auth.config import STATE_COOKIE_NAME

    client = TestClient(app)
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 307
    assert STATE_COOKIE_NAME in client.cookies
    cookie_val = client.cookies[STATE_COOKIE_NAME]
    assert "state=" in resp.headers["location"]
    assert cookie_val in resp.headers["location"]


def test_callback_rejects_cross_browser_state_login_csrf():
    """Verify /auth/callback rejects valid state if the browser lacks the bound session cookie."""
    client = TestClient(app)
    # Generate valid state from "another browser"
    valid_state_from_other_browser = create_state_token(purpose="login")

    # Victim browser visits callback without having the cookie
    resp = client.get(
        "/auth/callback",
        params={"code": "mock-code", "state": valid_state_from_other_browser},
    )
    assert resp.status_code == 400
    assert "Invalid or expired session state token" in resp.text


def test_callback_rejects_mismatched_state_cookie():
    """Verify /auth/callback rejects state if the browser cookie has a different state."""
    from application_services.auth.config import STATE_COOKIE_NAME

    client = TestClient(app)
    state1 = create_state_token(purpose="login")
    state2 = create_state_token(purpose="login")

    client.cookies.set(STATE_COOKIE_NAME, state1)
    resp = client.get(
        "/auth/callback",
        params={"code": "mock-code", "state": state2},
    )
    assert resp.status_code == 400
    assert "Invalid or expired session state token" in resp.text


def test_state_token_is_single_use():
    """Verify single_use=True invalidates the token upon first consumption to prevent replay."""
    state = create_state_token(purpose="login")

    # First verification with single_use=True succeeds
    payload1 = verify_state_token(state, expected_purpose="login", single_use=True)
    assert payload1 is not None
    assert payload1["purpose"] == "login"

    # Second verification with single_use=True must fail (replay attack prevented)
    payload2 = verify_state_token(state, expected_purpose="login", single_use=True)
    assert payload2 is None
