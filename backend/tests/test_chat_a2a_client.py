"""Chat's production A2A client calling the real Conversation Agent.

Chris runs as a real A2A application and Application Services' client calls it, so this
is an end-to-end test. The client's own tests are in Application Services' package.
"""

from unittest.mock import AsyncMock, patch

import httpx
from application_services.chat.a2a_client import send_message
from conversation_agent.routing import RoutingResult
from conversation_agent.run import create_app
from fastapi.testclient import TestClient


def test_chat_client_calls_real_chris(monkeypatch):
    """Chat's production client speaks to the actual ADK agent in its own app."""
    selection = AsyncMock(return_value=RoutingResult(status="no_match"))
    monkeypatch.setattr("conversation_agent.registry_client.select_agent", selection)
    answer = AsyncMock(return_value="Gemini answer.")
    monkeypatch.setattr("conversation_agent.gemini.answer", answer)
    monkeypatch.setenv("CHRIS_PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")
    chris = create_app()

    def http_client():
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=chris))

    with (
        TestClient(chris) as client,
        patch("application_services.chat.a2a_client._http_client", side_effect=http_client),
    ):
        reply = client.portal.call(
            send_message, "Hello Chris", [{"role": "user", "content": "Earlier"}]
        )
    assert reply.text == "Gemini answer."
    selection.assert_awaited_once_with(
        "Hello Chris", [{"role": "user", "content": "Earlier"}]
    )
    answer.assert_awaited_once_with(
        "Hello Chris", [{"role": "user", "content": "Earlier"}]
    )
