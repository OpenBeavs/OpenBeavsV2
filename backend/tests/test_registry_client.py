"""Chris's fallback and expert answers, as Chat's A2A client receives them.

These exercise the Conversation Agent and Application Services together: Chris runs
as a real A2A application, and Chat's production client calls it. Chris's registry
client on its own is tested in the Conversation Agent's package.
"""

from unittest.mock import AsyncMock

import httpx
import pytest
from conversation_agent import gemini, registry_client, routing
from conversation_agent.run import create_app
from fastapi.testclient import TestClient

from app.chat.a2a_client import ChrisUnavailable, send_message


@pytest.mark.parametrize(
    "result",
    [
        routing.RoutingResult(status="no_match"),
        routing.chris_error("registry_unreachable", retryable=True),
    ],
)
@pytest.mark.parametrize(
    "model_failure",
    [None, gemini.GeminiUnavailable("private details")],
)
def test_fallback_mode_answers_no_match_and_failures_with_gemini(
    monkeypatch, result, model_failure
) -> None:
    selection = AsyncMock(return_value=result)

    async def model_answer(message, history):
        selection.assert_awaited_once_with(message, history)
        if model_failure:
            raise model_failure
        return "Gemini answer."

    answer = AsyncMock(side_effect=model_answer)
    monkeypatch.setattr(registry_client, "select_agent", selection)
    monkeypatch.setattr(gemini, "answer", answer)
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")
    chris = create_app()
    monkeypatch.setattr(
        "app.chat.a2a_client._http_client",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=chris)),
    )
    with TestClient(chris) as client:
        if model_failure:
            with pytest.raises(ChrisUnavailable):
                client.portal.call(send_message, "Hello", [])
        else:
            reply = client.portal.call(send_message, "Hello", [])
            assert reply.text == "Gemini answer."
            assert reply.routing is None
    answer.assert_awaited_once_with("Hello", [])


def test_selected_expert_answers(monkeypatch) -> None:
    expert = AsyncMock(return_value="Expert answer.")
    monkeypatch.setattr("conversation_agent.expert_client.send_message", expert)
    selected = routing.RoutingResult(
        status="selected",
        agent=routing.SelectedAgent(
            id="library-agent",
            endpoint_url="https://example.com/a2a/",
            name="Library Agent",
            description="Finds research resources.",
        ),
    )
    monkeypatch.setattr(
        registry_client, "select_agent", AsyncMock(return_value=selected)
    )
    answer = AsyncMock(return_value="must not be used")
    monkeypatch.setattr(gemini, "answer", answer)
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")
    chris = create_app()
    monkeypatch.setattr(
        "app.chat.a2a_client._http_client",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=chris)),
    )
    with TestClient(chris) as client:
        reply = client.portal.call(send_message, "Hello", [])
    answer.assert_not_awaited()
    assert reply.routing.status == "selected"
    assert reply.routing.agent.id == "library-agent"
    assert reply.routing.agent.name == "Library Agent"
    assert reply.routing.agent.description == "Finds research resources."
    expert.assert_awaited_once_with(selected.agent.endpoint_url, "Hello", [])
    assert reply.text == "Expert answer."
