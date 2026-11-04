"""Registry contract and mandatory call behavior using the real A2A SDK."""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.chat.a2a_client import ChrisUnavailable, send_message
from app.chris import registry_client
from app.config import ConfigError
from app.main import app


def test_registry_request_sends_message_and_history(monkeypatch):
    """The SDK discovers the configured card and sends the selection contract."""
    requests = []
    monkeypatch.setenv("REGISTRY_A2A_URL", "http://registry.example.test/")

    def respond(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "name": "registry",
                    "supportedInterfaces": [
                        {
                            "url": "http://registry.example.test/",
                            "protocolBinding": "JSONRPC",
                            "protocolVersion": "1.0",
                        }
                    ],
                },
            )
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "message": {
                        "messageId": "selection",
                        "role": "ROLE_AGENT",
                        "parts": [{"text": '{"agent":"none"}'}],
                    }
                },
            },
        )

    monkeypatch.setattr(
        registry_client,
        "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    history = [{"role": "user", "content": "Earlier question"}]
    result = asyncio.run(registry_client.select_agent("Choose an agent", history))
    assert json.loads(result) == {"agent": "none"}
    assert [request.method for request in requests] == ["GET", "POST"]
    assert (
        str(requests[0].url)
        == "http://registry.example.test/.well-known/agent-card.json"
    )
    body = json.loads(requests[1].content)
    assert body["method"] == "SendMessage"
    assert body["params"]["message"]["parts"] == [{"text": "Choose an agent"}]
    assert body["params"]["metadata"] == {"history": history}


def test_chris_always_calls_registry_and_relays_reply(monkeypatch):
    """Even greetings invoke selection once; only conversational history is passed."""
    selection = AsyncMock(return_value='{"agent":"none"}')
    monkeypatch.setattr(registry_client, "select_agent", selection)
    monkeypatch.setenv("CHRIS_PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")
    monkeypatch.setattr(
        "app.chat.a2a_client._http_client",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )
    history = [{"role": "assistant", "content": "Earlier answer"}]
    with TestClient(app) as client:
        result = client.portal.call(send_message, "Hi", history)
    assert result == '{"agent":"none"}'
    selection.assert_awaited_once_with("Hi", history)


def test_registry_failure_fails_chris_without_fallback(monkeypatch):
    """No fake success or model answer can hide a failed mandatory registry call."""
    selection = AsyncMock(
        side_effect=registry_client.RegistryUnavailable("private error")
    )
    monkeypatch.setattr(registry_client, "select_agent", selection)
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")
    monkeypatch.setattr(
        "app.chat.a2a_client._http_client",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )
    with TestClient(app) as client, pytest.raises(ChrisUnavailable) as error:
        client.portal.call(send_message, "Hello", [])
    selection.assert_awaited_once_with("Hello", [])
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "reply",
    [
        {"agent": "none"},
        {"agent": {"id": "library-agent", "endpoint_url": "https://example.com/a2a/"}},
    ],
)
def test_selection_contract_accepts_both_outcomes(reply):
    """The registry may select an agent or explicitly report no match."""
    registry_client._validate_selection(json.dumps(reply))


@pytest.mark.parametrize(
    "reply",
    [{"agent": None}, {"agent": "unknown"}, {"agent": {"id": "library-agent"}}, {}],
)
def test_selection_contract_rejects_other_shapes(reply):
    """Missing fields and the old null sentinel do not satisfy the agreed contract."""
    with pytest.raises(ValueError):
        registry_client._validate_selection(json.dumps(reply))


@pytest.mark.parametrize(
    "endpoint", ["", "file:///registry", "http://host:bad/", "http://u:p@host/"]
)
def test_invalid_registry_url_fails_before_network(endpoint, monkeypatch):
    """Operator configuration errors never silently skip the registry step."""
    monkeypatch.setenv("REGISTRY_A2A_URL", endpoint)
    with pytest.raises(ConfigError, match="REGISTRY_A2A_URL"):
        asyncio.run(registry_client.select_agent("Hello", []))


@pytest.mark.parametrize("failure", ["timeout", "connection", "malformed"])
def test_registry_transport_errors_are_sanitized(failure, monkeypatch):
    """Upstream network and invalid-card details do not escape the adapter."""
    monkeypatch.setenv("REGISTRY_A2A_URL", "http://registry.example.test/")

    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private upstream details")
        if failure == "connection":
            raise httpx.ConnectError("private upstream details")
        return httpx.Response(200, text="private upstream details")

    monkeypatch.setattr(
        registry_client,
        "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    with pytest.raises(registry_client.RegistryUnavailable) as error:
        asyncio.run(registry_client.select_agent("Hello", []))
    assert "private" not in str(error.value)
