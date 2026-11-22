"""The chat API and the real Conversation Agent together, storing no conversation.

These run Chris as a real A2A application behind Application Services' chat API, so
they are end-to-end tests. The chat API's own tests are in Application Services'
package.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from application_services.db.base import ChatSystemBase
from application_services.db.session import get_db
from application_services.main import app
from application_services.models import Chat, Message
from conversation_agent.routing import RoutingResult
from conversation_agent.run import create_app as create_chris_app
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

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


def test_frontend_chat_uses_real_adk_chris(test_db, monkeypatch):
    """The frontend API calls the real A2A agent without storing its response."""
    selection = AsyncMock(return_value=RoutingResult(status="no_match"))
    monkeypatch.setattr("conversation_agent.registry_client.select_agent", selection)
    answer = AsyncMock(return_value="Gemini answer.")
    monkeypatch.setattr("conversation_agent.gemini.answer", answer)
    history = [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
    ]
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")
    monkeypatch.setenv("CHRIS_PUBLIC_URL", "http://testserver")
    chris = create_chris_app()
    requests = []

    def http_client():
        async def record(request):
            requests.append(request)

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=chris),
            event_hooks={"request": [record]},
        )

    with (
        TestClient(app) as client,
        patch("application_services.chat.a2a_client._http_client", side_effect=http_client),
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
    monkeypatch.setattr("conversation_agent.gemini.answer", answer)
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")
    monkeypatch.setenv("REGISTRY_A2A_URL", "http://registry.example.test/")
    chris = create_chris_app()
    monkeypatch.setattr(
        "application_services.chat.a2a_client._http_client",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=chris)),
    )

    def unavailable(request):
        raise httpx.ConnectError("Registry is not running", request=request)

    monkeypatch.setattr(
        "conversation_agent.registry_client._http_client",
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
