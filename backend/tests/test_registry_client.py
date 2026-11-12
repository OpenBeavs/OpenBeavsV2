"""Chris's registry client: the request it sends and how it reads the reply.

Uses the real A2A SDK against an in-memory fake registry. Pipeline-level behavior
(Chat -> Chris -> a real registry) is covered in ``tests/integration``.

The registry's reply is one text part holding compact JSON (``{"agent": {"id",
"endpoint_url"}}`` or ``{"agent": "none"}``); a failed selection is an A2A error whose
message is a short code.
"""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.chat.a2a_client import ChrisUnavailable, send_message
from app.chris import gemini, registry_client, routing
from app.main import app

RPC_URL = "http://registry.example.test/a2a/registry/"
SELECTED = {
    "agent": {"id": "library-agent", "endpoint_url": "https://example.com/a2a/"}
}
CARD = {
    "name": "registry",
    "supportedInterfaces": [
        {"url": RPC_URL, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
    ],
}


def fake_registry(monkeypatch, *, text=None, error=None, seen: list | None = None):
    """Point Chris at an in-memory registry that replies with ``text`` or fails with
    the A2A error ``(rpc_code, message)``."""
    monkeypatch.setenv("REGISTRY_A2A_URL", "http://registry.example.test/a2a/registry")

    def respond(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=CARD)
        body = json.loads(request.content)
        if error is not None:
            rpc_code, message = error
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": rpc_code, "message": message},
                },
            )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "message": {
                        "messageId": "selection",
                        "role": "ROLE_AGENT",
                        "parts": [{"text": text}],
                    }
                },
            },
        )

    monkeypatch.setattr(
        registry_client,
        "_http_client",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )


def select(message="Choose", history=None):
    return asyncio.run(registry_client.select_agent(message, history or []))


class TestRequest:
    def test_it_discovers_the_card_then_sends_question_and_history(
        self, monkeypatch
    ) -> None:
        seen: list[httpx.Request] = []
        fake_registry(monkeypatch, text='{"agent":"none"}', seen=seen)
        history = [{"role": "user", "content": "Earlier question"}]
        select("Choose an agent", history)

        assert [r.method for r in seen] == ["GET", "POST"]
        assert str(seen[0].url) == (
            "http://registry.example.test/a2a/registry/.well-known/agent-card.json"
        )
        body = json.loads(seen[1].content)
        assert body["method"] == "SendMessage"
        parts = body["params"]["message"]["parts"]
        assert parts[0] == {"text": "Choose an agent"}
        assert parts[1]["data"] == {"history": history}  # the documented contract
        assert "history" not in body["params"].get("metadata", {})

    def test_no_credential_is_sent(self, monkeypatch) -> None:
        """Local-development stage: no token (a deployed registry needs one later)."""
        seen: list[httpx.Request] = []
        fake_registry(monkeypatch, text='{"agent":"none"}', seen=seen)
        select()
        assert all("authorization" not in r.headers for r in seen)


class TestReadingTheReply:
    def test_selected(self, monkeypatch) -> None:
        fake_registry(monkeypatch, text=json.dumps(SELECTED))
        result = select()
        assert result.status == routing.SELECTED
        assert result.agent.id == "library-agent"
        assert result.agent.endpoint_url == "https://example.com/a2a/"

    def test_no_match(self, monkeypatch) -> None:
        fake_registry(monkeypatch, text='{"agent":"none"}')
        result = select()
        assert result.status == routing.NO_MATCH and result.agent is None

    def test_the_task_form_of_a_reply_is_read_too(self, monkeypatch) -> None:
        """A completed Task with the JSON in an artifact is accepted (as before)."""
        monkeypatch.setenv(
            "REGISTRY_A2A_URL", "http://registry.example.test/a2a/registry"
        )

        def respond(request):
            if request.method == "GET":
                return httpx.Response(200, json=CARD)
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "task": {
                            "id": "t",
                            "status": {"state": "TASK_STATE_COMPLETED"},
                            "artifacts": [
                                {
                                    "artifactId": "a",
                                    "parts": [{"text": '{"agent":"none"}'}],
                                }
                            ],
                        }
                    },
                },
            )

        monkeypatch.setattr(
            registry_client,
            "_http_client",
            lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        assert select().status == routing.NO_MATCH

    @pytest.mark.parametrize(
        "bad",
        [
            "prose",
            "{nope",
            "[]",
            "{}",
            '{"agent": null}',
            '{"agent": "unknown"}',
            '{"agent": {"id": "x"}}',
            '{"agent": {"id": "x", "endpoint_url": "https://e.test", "name": "X"}}',
            '{"agent": "none", "confidence": 0.9}',
            '{"status": "selected", "agent": {"id": "x", "endpoint_url": "https://e.test"}}',
        ],
    )
    def test_anything_else_is_an_invalid_reply(self, bad, monkeypatch) -> None:
        fake_registry(monkeypatch, text=bad)
        result = select()
        assert result.error_code == "registry_invalid_reply"
        assert result.source == "chris" and result.retryable is False


class TestRegistryReportedFailures:
    """The registry fails with an A2A error whose message is a code."""

    @pytest.mark.parametrize(
        ("code", "retryable"),
        [
            ("selection_unavailable", True),
            ("selection_busy", True),
            ("agent_unavailable", True),
            ("not_configured", False),
            ("registry_capacity_exceeded", False),
        ],
    )
    def test_the_code_and_a_registry_source_are_kept(
        self, code, retryable, monkeypatch
    ) -> None:
        fake_registry(monkeypatch, error=(-32603, code))
        result = select()
        assert result.status == routing.ERROR
        assert (result.error_code, result.retryable, result.source) == (
            code,
            retryable,
            "registry",
        )

    def test_invalid_params_maps_to_invalid_request(self, monkeypatch) -> None:
        fake_registry(monkeypatch, error=(-32602, "invalid_request"))
        result = select()
        assert (result.error_code, result.source) == ("invalid_request", "registry")

    @pytest.mark.parametrize("message", ["surprise", "SECRET internal detail", ""])
    def test_an_unknown_message_is_not_trusted_as_a_code(
        self, message, monkeypatch
    ) -> None:
        fake_registry(monkeypatch, error=(-32603, message))
        result = select()
        assert result.error_code == "registry_protocol_error"
        assert result.source == "chris" and "SECRET" not in repr(result)


class TestFailuresAreResultsNotExceptions:
    @pytest.mark.parametrize(
        "endpoint", ["file:///registry", "http://host:bad/", "http://u:p@host/"]
    )
    def test_a_bad_registry_url_is_reported_before_any_network(
        self, endpoint, monkeypatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_A2A_URL", endpoint)
        result = select()
        assert result.error_code == "registry_not_configured"
        assert result.retryable is False

    @pytest.mark.parametrize(
        ("failure", "code"),
        [
            ("timeout", "registry_timeout"),
            ("connection", "registry_unreachable"),
            ("malformed", "registry_unreachable"),  # the card is not valid JSON
        ],
    )
    def test_transport_errors_are_coded_and_sanitized(
        self, failure, code, monkeypatch
    ) -> None:
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
            lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        result = select()
        assert result.error_code == code and result.source == "chris"
        assert "private" not in repr(result)

    def test_the_whole_exchange_has_one_deadline(self, monkeypatch) -> None:
        monkeypatch.setenv("REGISTRY_A2A_URL", "http://registry.example.test/")
        monkeypatch.setenv("REGISTRY_A2A_TIMEOUT_SECONDS", "1")

        async def respond(request):
            await asyncio.sleep(5)
            return httpx.Response(200)

        monkeypatch.setattr(
            registry_client,
            "_http_client",
            lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        assert select().error_code == "registry_timeout"


class TestTimeoutSetting:
    def test_default_covers_the_registry_worst_case(self, monkeypatch) -> None:
        monkeypatch.delenv("REGISTRY_A2A_TIMEOUT_SECONDS", raising=False)
        assert registry_client.timeout_seconds() == 14.0

    def test_setting_is_used(self, monkeypatch) -> None:
        monkeypatch.setenv("REGISTRY_A2A_TIMEOUT_SECONDS", "6")
        assert registry_client.timeout_seconds() == 6

    @pytest.mark.parametrize("bad", ["0", "-1", "abc", "nan", "inf", "61", ""])
    def test_bad_values_use_the_default(self, bad, monkeypatch) -> None:
        monkeypatch.setenv("REGISTRY_A2A_TIMEOUT_SECONDS", bad)
        assert registry_client.timeout_seconds() == 14.0


@pytest.mark.parametrize("mode", [None, "false"])
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
    monkeypatch, result, model_failure, mode
) -> None:
    """The default and explicit fallback mode answer no-match and failures."""
    if mode is None:
        monkeypatch.delenv("CHRIS_SELECTION_ONLY", raising=False)
    else:
        monkeypatch.setenv("CHRIS_SELECTION_ONLY", mode)
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
    monkeypatch.setattr(
        "app.chat.a2a_client._http_client",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )
    with TestClient(app) as client:
        if model_failure:
            with pytest.raises(ChrisUnavailable):
                client.portal.call(send_message, "Hello", [])
        else:
            reply = client.portal.call(send_message, "Hello", [])
            assert reply.text == "Gemini answer."
            assert reply.routing is None
    answer.assert_awaited_once_with("Hello", [])


def test_a_selection_is_reported_and_never_answered_by_gemini(monkeypatch) -> None:
    selected = routing.RoutingResult(
        status="selected",
        agent=routing.SelectedAgent(
            id="library-agent", endpoint_url="https://example.com/a2a/"
        ),
    )
    monkeypatch.setattr(
        registry_client, "select_agent", AsyncMock(return_value=selected)
    )
    answer = AsyncMock(return_value="must not be used")
    monkeypatch.setattr(gemini, "answer", answer)
    monkeypatch.setenv("CHRIS_A2A_URL", "http://testserver/chris/a2a/")
    monkeypatch.setattr(
        "app.chat.a2a_client._http_client",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )
    with TestClient(app) as client:
        reply = client.portal.call(send_message, "Hello", [])
    answer.assert_not_awaited()
    assert reply.routing.status == "selected"
    assert reply.routing.agent.id == "library-agent"
    assert reply.text == "I found a specialist for your question."
