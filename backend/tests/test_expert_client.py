"""Exercise expert dispatch through real SDK serialization without external traffic."""

import asyncio
import json

import httpx
import pytest

from app.chris import expert_client

ENDPOINT = "https://expert.example.test/rpc"


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setenv("CHRIS_EXPERT_A2A_VERSION", "1.0")
    monkeypatch.setenv("CHRIS_EXPERT_TIMEOUT_SECONDS", "30")
    # Keep real URL validation; only DNS is deterministic.
    monkeypatch.setattr(
        "app.registry.security.default_resolver", lambda host: ["8.8.8.8"]
    )
    requests = []

    def install(result=None, status=200, failure=None):
        def respond(request):
            requests.append(request)
            if failure:
                raise failure
            return httpx.Response(status, json={
                "jsonrpc": "2.0", "id": json.loads(request.content)["id"],
                "result": result,
            }, headers={"location": "https://other.example.test/rpc"})
        monkeypatch.setattr(
            expert_client, "_http_client",
            lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        return requests
    return install


@pytest.mark.parametrize("version", [None, "1.0", "0.3"])
@pytest.mark.parametrize("task", [False, True])
def test_wire_answer_and_history(wire, monkeypatch, version, task):
    if version is None:
        monkeypatch.delenv("CHRIS_EXPERT_A2A_VERSION")
        version = "0.3"
    else:
        monkeypatch.setenv("CHRIS_EXPERT_A2A_VERSION", version)
    part = {"text": "42"}
    if version == "0.3":
        part["kind"] = "text"
        result = (
            {"kind": "task", "id": "t", "contextId": "c",
             "status": {"state": "completed"},
             "artifacts": [{"artifactId": "a", "parts": [part]}]}
            if task else
            {"kind": "message", "messageId": "r", "role": "agent", "parts": [part]}
        )
    else:
        result = (
            {"task": {"id": "t", "status": {"state": "TASK_STATE_COMPLETED"},
                      "artifacts": [{"artifactId": "a", "parts": [part]}]}}
            if task else
            {"message": {"messageId": "r", "role": "ROLE_AGENT", "parts": [part]}}
        )
    requests = wire(result)
    history = [{"role": "user", "content": "Earlier"}]
    assert asyncio.run(expert_client.send_message(ENDPOINT, "Question", history)) == "42"
    assert len(requests) == 1
    req = requests[0]
    assert str(req.url) == ENDPOINT
    assert "authorization" not in req.headers
    body = json.loads(req.content)
    assert body["method"] == ("SendMessage" if version == "1.0" else "message/send")
    assert body["params"]["metadata"] == {"history": history}
    assert body["params"]["message"]["parts"][0]["text"] == "Question"


@pytest.mark.parametrize("result", [
    {}, {"message": {"parts": [{"text": " "}]}},
    {"task": {"status": {"state": "TASK_STATE_WORKING"}}},
    {"task": {"status": {"state": "TASK_STATE_FAILED"}}},
    {"task": {"status": {"state": "TASK_STATE_COMPLETED"}}},
])
def test_incomplete_or_empty_reply_fails(wire, result):
    wire(result)
    with pytest.raises(expert_client.ExpertUnavailable, match="temporarily unavailable"):
        asyncio.run(expert_client.send_message(ENDPOINT, "q", []))


@pytest.mark.parametrize("status", [302, 401, 403, 500])
def test_http_failure_does_not_retry_or_follow_redirect(wire, status, caplog):
    requests = wire(status=status)
    with pytest.raises(expert_client.ExpertUnavailable):
        asyncio.run(expert_client.send_message(ENDPOINT, "q", []))
    assert len(requests) == 1
    assert f"http_status={status}" in caplog.text
    code = "expert_auth_rejected" if status in (401, 403) else "expert_http_error"
    assert code in caplog.text


@pytest.mark.parametrize("endpoint", [
    "https://127.0.0.1/rpc", "https://10.0.0.1/rpc",
    "https://169.254.169.254/rpc", "https://metadata.google.internal/rpc",
    "https://user:password@example.test/rpc", "http://example.test/rpc",
    "file:///tmp/rpc", "https://example.test/rpc#fragment",
    "https://example.test/rpc?token=placeholder", "https://example.test/ bad",
])
def test_unsafe_destination_never_gets_a_request(wire, endpoint):
    requests = wire()
    with pytest.raises(expert_client.ExpertUnavailable):
        asyncio.run(expert_client.send_message(endpoint, "q", []))
    assert requests == []


def test_dns_private_address_is_rejected(wire, monkeypatch):
    requests = wire()
    monkeypatch.setattr(
        "app.registry.security.default_resolver", lambda host: ["10.1.2.3"]
    )
    with pytest.raises(expert_client.ExpertUnavailable):
        asyncio.run(expert_client.send_message(ENDPOINT, "q", []))
    assert requests == []


def test_deadline_cancels_exchange(wire, monkeypatch):
    wire()
    monkeypatch.setenv("CHRIS_EXPERT_TIMEOUT_SECONDS", "1")

    async def respond(request):
        await asyncio.sleep(5)
        return httpx.Response(200)

    monkeypatch.setattr(expert_client, "_http_client", lambda timeout:
                        httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    with pytest.raises(expert_client.ExpertUnavailable):
        asyncio.run(expert_client.send_message(ENDPOINT, "q", []))


@pytest.mark.parametrize("failure", [httpx.ConnectError("private"),
                                     httpx.ReadTimeout("private")])
def test_transport_error_is_sanitized(wire, failure, caplog):
    wire(failure=failure)
    with pytest.raises(expert_client.ExpertUnavailable) as error:
        asyncio.run(expert_client.send_message(ENDPOINT, "q", []))
    assert "private" not in str(error.value) + caplog.text
    code = "expert_timeout" if isinstance(failure, httpx.TimeoutException) else "expert_unreachable"
    assert f"code={code}" in caplog.text
