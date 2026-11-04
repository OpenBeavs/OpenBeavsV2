"""Verify chat's SDK transport, failure handling, and real ADK integration."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.chat.a2a_client import ChrisUnavailable, send_message
from app.config import ConfigError
from app.main import app


def test_chat_client_calls_real_chris(monkeypatch):
    """Chat's production client speaks to the actual mounted ADK agent."""
    selection = AsyncMock(return_value='{"agent":"none"}')
    monkeypatch.setattr("app.chris.registry_client.select_agent", selection)
    monkeypatch.setenv("CHRIS_PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")

    def http_client():
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app))

    with (
        TestClient(app) as client,
        patch("app.chat.a2a_client._http_client", side_effect=http_client),
    ):
        reply = client.portal.call(
            send_message, "Hello Chris", [{"role": "user", "content": "Earlier"}]
        )
    assert reply == '{"agent":"none"}'
    selection.assert_awaited_once_with(
        "Hello Chris", [{"role": "user", "content": "Earlier"}]
    )


def test_wire_request_contains_history_without_identity(monkeypatch):
    """Only the authorized context is replayed, without database access tokens."""
    monkeypatch.setenv("CHRIS_A2A_URL", "http://chris.example.test/chris/a2a/")
    requests = []

    def respond(request):
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "message": {
                        "messageId": "reply",
                        "role": "ROLE_AGENT",
                        "parts": [{"text": "Hello"}],
                    }
                },
            },
        )

    history = [{"role": "assistant", "content": "Earlier answer"}]
    with patch(
        "app.chat.a2a_client._http_client",
        side_effect=lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ):
        assert asyncio.run(send_message("New question", history)) == "Hello"
    assert len(requests) == 1
    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == "http://chris.example.test/chris/a2a/"
    assert request.headers["A2A-Version"] == "1.0"
    assert body["method"] == "SendMessage"
    assert body["params"]["message"]["parts"] == [{"text": "New question"}]
    assert body["params"]["metadata"] == {"history": history}


@pytest.mark.parametrize(
    "result",
    [
        {"task": {"id": "task", "status": {"state": "TASK_STATE_FAILED"}}},
        {"task": {"id": "task", "status": {"state": "TASK_STATE_WORKING"}}},
        {"task": {"id": "task", "status": {"state": "TASK_STATE_COMPLETED"}}},
        {"message": {"messageId": "reply", "role": "ROLE_AGENT", "parts": []}},
    ],
)
def test_failed_unfinished_and_empty_replies_are_rejected(result):
    """Never persist an unfinished task or an empty/failed result as an answer."""

    def respond(request):
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": result,
            },
        )

    with (
        patch(
            "app.chat.a2a_client._http_client",
            side_effect=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            ),
        ),
        pytest.raises(ChrisUnavailable),
    ):
        asyncio.run(send_message("Hello", []))


@pytest.mark.parametrize("failure", ["timeout", "connection", "rpc", "malformed"])
def test_transport_errors_are_sanitized(failure):
    """Remote error bodies and transport details never reach the frontend."""

    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private upstream details")
        if failure == "connection":
            raise httpx.ConnectError("private upstream details")
        if failure == "malformed":
            return httpx.Response(200, text="private upstream details")
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32603, "message": "private upstream details"},
            },
        )

    with (
        patch(
            "app.chat.a2a_client._http_client",
            side_effect=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            ),
        ),
        pytest.raises(ChrisUnavailable, match="temporarily unavailable") as error,
    ):
        asyncio.run(send_message("Hello", []))
    assert "private" not in str(error.value)


def test_invalid_destination_is_configuration_error(monkeypatch):
    """A caller cannot supply credentials or query parameters in the URL."""
    monkeypatch.setenv("CHRIS_A2A_URL", "file:///tmp/chris")
    with pytest.raises(ConfigError, match="CHRIS_A2A_URL"):
        asyncio.run(send_message("Hello", []))


def test_whole_call_has_a_deadline(monkeypatch):
    """The overall deadline bounds slow transports as well as SDK processing."""
    monkeypatch.setattr("app.chat.a2a_client.TIMEOUT_SECONDS", 0.01)

    async def respond(request):
        await asyncio.sleep(1)
        return httpx.Response(200)

    with (
        patch(
            "app.chat.a2a_client._http_client",
            side_effect=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            ),
        ),
        pytest.raises(ChrisUnavailable),
    ):
        asyncio.run(send_message("Hello", []))
