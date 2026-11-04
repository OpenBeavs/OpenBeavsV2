"""Exercise Chris through the real mounted ADK app and A2A SDK, without a model."""

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState
from fastapi.testclient import TestClient

from app.main import app

CARD_PATH = "/chris/a2a/.well-known/agent-card.json"
RPC_PATH = "/chris/a2a/"


@pytest.fixture(autouse=True)
def local_config(monkeypatch):
    """No model credentials or external server are needed for these tests."""
    monkeypatch.setenv("CHRIS_PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("CHRIS_MODEL", "")


def test_generated_card_and_repeated_startup():
    """The parent's lifespan initializes discovery without accumulating mounts."""
    route_count = len(app.routes)
    for _ in range(2):
        with TestClient(app) as client:
            response = client.get(CARD_PATH)
            assert response.status_code == 200
            card = response.json()
            assert card["name"] == "chris"
            assert card["supportedInterfaces"] == [
                {
                    "url": f"http://testserver{RPC_PATH}",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0",
                }
            ]
            assert not card.get("capabilities", {}).get("streaming", False)
            assert card["defaultInputModes"] == ["text/plain"]
            assert card["skills"]
            assert client.get("/chris/.well-known/agent.json").status_code == 404
        assert len(app.routes) == route_count


@pytest.mark.parametrize("text", ["Hello Chris", "   "])
def test_sdk_discovery_and_message(text, monkeypatch):
    """A real SDK client discovers the mounted endpoint and receives its result."""
    selection = AsyncMock(return_value='{"agent":"none"}')
    monkeypatch.setattr("app.chris.registry_client.select_agent", selection)

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            card = await A2ACardResolver(
                httpx_client=http, base_url=f"http://testserver{RPC_PATH}"
            ).get_agent_card()
            agent_client = ClientFactory(
                ClientConfig(httpx_client=http, streaming=False)
            ).create(card)
            try:
                return [
                    response
                    async for response in agent_client.send_message(
                        SendMessageRequest(
                            message=Message(
                                message_id=str(uuid.uuid4()),
                                role=Role.ROLE_USER,
                                parts=[Part(text=text)],
                            )
                        )
                    )
                ]
            finally:
                await agent_client.close()

    with (
        patch("app.chat.service.handle_message", new_callable=AsyncMock) as chat,
        TestClient(app) as client,
    ):
        responses = client.portal.call(send)
    chat.assert_not_awaited()
    assert len(responses) == 1
    task = responses[0].task
    if text.strip():
        assert task.status.state == TaskState.TASK_STATE_COMPLETED
        assert [p.text for a in task.artifacts for p in a.parts] == ['{"agent":"none"}']
        selection.assert_awaited_once_with(text, [])
    else:
        assert task.status.state == TaskState.TASK_STATE_FAILED
        selection.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {"message": "frontend payload is not an A2A request"},
        {"jsonrpc": "2.0", "id": "bad", "method": "SendMessage", "params": {}},
        {"jsonrpc": "2.0", "id": "bad", "method": "unknown", "params": {}},
    ],
)
def test_sdk_rejects_malformed_rpc(body):
    """Protocol validation is provided by the SDK instead of a handwritten route."""
    with TestClient(app) as client:
        response = client.post(RPC_PATH, json=body, headers={"A2A-Version": "1.0"})
    assert response.status_code in (200, 400, 422)
    assert "error" in response.json()


def test_public_url_configuration(monkeypatch):
    """Discovery advertises the configured deployment URL, not localhost."""
    monkeypatch.setenv("CHRIS_PUBLIC_URL", "https://hub.example.test")
    with TestClient(app) as client:
        card = client.get(CARD_PATH).json()
    assert (
        card["supportedInterfaces"][0]["url"] == "https://hub.example.test/chris/a2a/"
    )
