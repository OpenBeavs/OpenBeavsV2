"""Prevent anonymous A2A callers from reading retained tasks or sessions."""

import asyncio
import gc
import weakref
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from google.adk.sessions import InMemorySessionService

from app.chris.transport import MessageOnlyTaskStore
from app.main import app

RPC_PATH = "/chris/a2a/"
HEADERS = {"A2A-Version": "1.0"}


@pytest.fixture(autouse=True)
def local_chris(monkeypatch):
    """Keep registry and Gemini calls local while exercising real SDK handlers."""
    monkeypatch.setenv("CHRIS_PUBLIC_URL", "http://testserver")
    monkeypatch.setattr(
        "app.chris.registry_client.select_agent",
        AsyncMock(return_value='{"agent":"none"}'),
    )
    monkeypatch.setattr(
        "app.chris.gemini.answer", AsyncMock(return_value="Private answer")
    )


def send_turn(client, message="Private question", **references):
    """Send a blocking turn and expose its task IDs for retrieval attacks."""
    response = client.post(
        RPC_PATH,
        headers=HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": "send",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "turn",
                    "role": "ROLE_USER",
                    "parts": [{"text": message}],
                    **references,
                }
            },
        },
    )
    assert response.status_code == 200
    return response.json()["result"]["task"]


@pytest.mark.parametrize(
    "method",
    [
        "ListTasks",
        "GetTask",
        "SubscribeToTask",
        "CancelTask",
        "tasks/get",
        "tasks/resubscribe",
        "tasks/cancel",
    ],
)
def test_tasks_cannot_be_enumerated_or_read(method):
    """Knowing a real task/context ID must not expose another request's data."""
    with TestClient(app) as client:
        task = send_turn(client)
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        params = (
            {"includeArtifacts": True}
            if method == "ListTasks"
            else {"id": task["id"]}
        )
        response = client.post(
            RPC_PATH,
            headers=HEADERS,
            json={"jsonrpc": "2.0", "id": "read", "method": method, "params": params},
        )
        assert "error" in response.json()
        assert "Private question" not in response.text
        assert "Private answer" not in response.text


def test_prior_task_cannot_be_resumed():
    """SendMessage cannot use a known task ID to bypass retrieval restrictions."""
    with TestClient(app) as client:
        task = send_turn(client)
        response = client.post(
            RPC_PATH,
            headers=HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": "resume",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "next",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Continue"}],
                        "taskId": task["id"],
                        "contextId": task["contextId"],
                    }
                },
            },
        )
        assert "error" in response.json()
        assert "Private question" not in response.text
        assert "Private answer" not in response.text


def test_finished_requests_release_task_and_session_stores(monkeypatch):
    """Completed turns must not accumulate stores while the app is still running."""
    stores = []
    sessions = []

    def task_store():
        store = MessageOnlyTaskStore()
        stores.append(weakref.ref(store))
        return store

    def session_service():
        service = InMemorySessionService()
        sessions.append(weakref.ref(service))
        return service

    monkeypatch.setattr("app.chris.transport.MessageOnlyTaskStore", task_store)
    monkeypatch.setattr(
        "google.adk.a2a.utils.agent_to_a2a.InMemorySessionService", session_service
    )

    async def collect_finished_requests():
        # Let SDK completion callbacks finish before collecting request cycles.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        gc.collect()

    with TestClient(app) as client:
        for _ in range(3):
            send_turn(client, contextId="same-untrusted-context")
        client.portal.call(collect_finished_requests)
        assert len(stores) == len(sessions) == 3
        assert all(reference() is None for reference in stores + sessions)
