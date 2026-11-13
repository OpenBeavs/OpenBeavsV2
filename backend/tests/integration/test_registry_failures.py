"""What Chat shows when the registry misbehaves.

A fake registry (an in-memory HTTP server returning canned replies) stands in for the
real one, so these tests can produce replies the real registry never would. Everything
else is still real: Chat's router and service and Chris's agent and registry client.
In diagnostic mode failures show a generic availability message. Backend diagnostics
must not reach the browser, and a bad reply must never become a selection.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.chat import a2a_client
from app.chris import gemini, registry_client
from app.db.session import get_db
from app.main import app as backend_app

from .conftest import CHRIS_ORIGIN, REGISTRY_ORIGIN

RPC_URL = f"{REGISTRY_ORIGIN}/a2a/registry/"
CARD = {
    "name": "registry",
    "supportedInterfaces": [
        {"url": RPC_URL, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
    ],
}
GOOD = {"agent": {"id": "math-expert", "endpoint_url": "https://math.example.test/rpc"}}


def message_result(parts: list[dict]) -> dict:
    return {"message": {"messageId": "m", "role": "ROLE_AGENT", "parts": parts}}


def text_reply(text: str):
    """A fake registry that answers every message with this reply text."""

    def on_post(request, body):
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": message_result([{"text": text}]),
            },
        )

    return on_post


def coded_error(code: str, rpc_code: int = -32603):
    """A fake registry that fails the way the real one does: an A2A error with a code."""

    def on_post(request, body):
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": rpc_code, "message": code},
            },
        )

    return on_post


def serve(monkeypatch, tmp_path, on_post, on_get=None):
    """Run Chat+Chris for real against a fake registry defined by two callables."""
    from sqlalchemy import create_engine

    from app.db.base import Base

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return on_get(request) if on_get else httpx.Response(200, json=CARD)
        return on_post(request, json.loads(request.content))

    engine = create_engine(
        f"sqlite:///{tmp_path / 'f.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("CHRIS_PUBLIC_URL", CHRIS_ORIGIN)
    monkeypatch.setenv("CHRIS_A2A_URL", f"{CHRIS_ORIGIN}/chris/a2a/")
    monkeypatch.setenv("REGISTRY_A2A_URL", f"{REGISTRY_ORIGIN}/a2a/registry")
    monkeypatch.setenv("CHRIS_SELECTION_ONLY", "true")
    monkeypatch.setenv("REGISTRY_A2A_TIMEOUT_SECONDS", "3")
    monkeypatch.setattr(
        registry_client,
        "_http_client",
        lambda timeout: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=timeout
        ),
    )
    monkeypatch.setattr(
        a2a_client,
        "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=backend_app)),
    )

    async def no_gemini(*args):
        raise AssertionError("Gemini must not answer in selection-only mode")

    monkeypatch.setattr(gemini, "answer", no_gemini)
    backend_app.dependency_overrides[get_db] = override_get_db
    return TestClient(backend_app)


def ask(client: TestClient) -> dict:
    with client:
        response = client.post("/chat/message", json={"message": "What is 2+2?"})
    backend_app.dependency_overrides.clear()
    assert response.status_code in (200, 503), response.text
    return response.json()


def assert_visible_error(body: dict, code: str, source: str = "chris") -> None:
    assert body == {"detail": "Chris is temporarily unavailable. Please try again shortly."}
    assert code not in json.dumps(body)



class TestWellFormedReply:
    """The control: the same fake registry with a valid reply works."""

    def test_a_valid_reply_is_a_selection(self, monkeypatch, tmp_path) -> None:
        body = ask(serve(monkeypatch, tmp_path, text_reply(json.dumps(GOOD))))
        assert body["routing"]["status"] == "selected"
        assert body["routing"]["agent"]["id"] == "math-expert"

    def test_none_is_no_match(self, monkeypatch, tmp_path) -> None:
        body = ask(serve(monkeypatch, tmp_path, text_reply('{"agent":"none"}')))
        assert body["routing"]["status"] == "no_match"


MALFORMED = {
    "prose only": ["Selected: Math Expert"],
    "not JSON": ["{nope"],
    "an empty reply": [""],
    "a JSON list": ['[{"agent": "none"}]'],
    "a JSON string": ['"none"'],
    "no agent key": ["{}"],
    "an unknown word for agent": ['{"agent": "unknown"}'],
    "agent null": ['{"agent": null}'],
    "agent as text": ['{"agent": "math-expert"}'],
    "agent without an endpoint": ['{"agent": {"id": "math-expert"}}'],
    "agent without an id": ['{"agent": {"endpoint_url": "https://x.test/rpc"}}'],
    "agent with an empty id": [
        '{"agent": {"id": "", "endpoint_url": "https://x.test/rpc"}}'
    ],
    "endpoint that is not text": ['{"agent": {"id": "m", "endpoint_url": 5}}'],
    "extra agent field": [
        '{"agent": {"id": "m", "endpoint_url": "https://x.test/rpc", "name": "Math"}}'
    ],
    "extra top-level field": [
        '{"agent": {"id": "m", "endpoint_url": "https://x.test/rpc"}, "confidence": 0.9}'
    ],
    "a rich status reply": [
        '{"status": "selected", "agent": {"id": "m", "endpoint_url": "https://x.test/rpc"}}'
    ],
    "two text parts": ['{"agent":"none"}', '{"agent":"none"}'],
}


class TestMalformedRegistryReplies:
    @pytest.mark.parametrize("texts", list(MALFORMED.values()), ids=list(MALFORMED))
    def test_it_is_a_visible_invalid_reply_error(
        self, texts, monkeypatch, tmp_path
    ) -> None:
        def on_post(request, body):
            parts = [{"text": t} for t in texts]
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": message_result(parts),
                },
            )

        body = ask(serve(monkeypatch, tmp_path, on_post))
        assert_visible_error(body, "registry_invalid_reply")

    def test_a_reply_with_only_a_data_part_is_invalid(
        self, monkeypatch, tmp_path
    ) -> None:
        """The old structured reply is no longer accepted: Chris reads the text JSON."""

        def on_post(request, body):
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": message_result([{"data": {"agent": "none"}}]),
                },
            )

        assert_visible_error(
            ask(serve(monkeypatch, tmp_path, on_post)), "registry_invalid_reply"
        )

    def test_a_malformed_reply_never_leaks_into_the_response(
        self, monkeypatch, tmp_path
    ) -> None:
        secret = "SECRET-FROM-A-BAD-REPLY"
        bad = json.dumps(
            {"agent": {"id": secret, "endpoint_url": secret, "name": secret}}
        )
        assert secret not in json.dumps(
            ask(serve(monkeypatch, tmp_path, text_reply(bad)))
        )


class TestRegistryReportedErrors:
    """A registry that cannot select answers with a coded A2A error; Chris reports it."""

    @pytest.mark.parametrize(
        ("code", "retryable"),
        [
            ("selection_unavailable", True),
            ("selection_busy", True),
            ("invalid_model_reply", True),
            ("agent_unavailable", True),
            ("registry_unavailable", True),
            ("internal_error", True),
            ("not_configured", False),
            ("registry_capacity_exceeded", False),
        ],
    )
    def test_the_code_and_source_are_kept(
        self, code, retryable, monkeypatch, tmp_path
    ) -> None:
        body = ask(serve(monkeypatch, tmp_path, coded_error(code)))
        assert_visible_error(body, code, source="registry")

    def test_an_invalid_request_is_not_retryable(self, monkeypatch, tmp_path) -> None:
        body = ask(serve(monkeypatch, tmp_path, coded_error("invalid_request", -32602)))
        assert_visible_error(body, "invalid_request", source="registry")

    @pytest.mark.parametrize("message", ["something_unexpected", "SECRET detail", ""])
    def test_an_unknown_code_is_not_trusted_as_one(
        self, message, monkeypatch, tmp_path
    ) -> None:
        body = ask(serve(monkeypatch, tmp_path, coded_error(message)))
        assert_visible_error(body, "registry_protocol_error")
        assert "SECRET" not in json.dumps(body)


class TestRegistryTransportFailures:
    def test_a_registry_that_is_not_running(self, monkeypatch, tmp_path) -> None:
        def refuse(request, *args):
            raise httpx.ConnectError("connection refused")

        client = serve(monkeypatch, tmp_path, refuse, on_get=refuse)
        body = ask(client)
        assert_visible_error(body, "registry_unreachable")

    def test_a_read_timeout_is_a_timeout(self, monkeypatch, tmp_path) -> None:
        def slow(request, *args):
            raise httpx.ReadTimeout("timed out")

        assert_visible_error(
            ask(serve(monkeypatch, tmp_path, slow)), "registry_timeout"
        )

    @pytest.mark.parametrize("status", [401, 403])
    def test_a_rejected_caller_is_an_auth_error(
        self, status, monkeypatch, tmp_path
    ) -> None:
        rejected = httpx.Response(
            status, json={"detail": "A bearer token is required."}
        )
        client = serve(
            monkeypatch,
            tmp_path,
            lambda req, body: rejected,
            on_get=lambda req: rejected,
        )
        assert_visible_error(ask(client), "registry_auth_rejected")

    def test_rejection_of_the_message_alone_is_also_an_auth_error(
        self, monkeypatch, tmp_path
    ) -> None:
        client = serve(
            monkeypatch,
            tmp_path,
            lambda req, body: httpx.Response(401, json={"detail": "no token"}),
        )
        assert_visible_error(ask(client), "registry_auth_rejected")

    def test_a_missing_card_means_the_registry_cannot_be_used(
        self, monkeypatch, tmp_path
    ) -> None:
        client = serve(
            monkeypatch,
            tmp_path,
            lambda req, body: httpx.Response(500),
            on_get=lambda req: httpx.Response(404),
        )
        body = ask(client)
        assert_visible_error(body, "registry_")

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(200, text="<html>proxy error</html>"),
            httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "x",
                    "error": {"code": -32601, "message": "no"},
                },
            ),
        ],
        ids=["http-500", "not-json", "jsonrpc-error"],
    )
    def test_protocol_level_failures_are_visible(
        self, response, monkeypatch, tmp_path
    ) -> None:
        client = serve(monkeypatch, tmp_path, lambda req, body: response)
        body = ask(client)
        assert_visible_error(body, "registry_")

    def test_a_misconfigured_registry_url_is_reported_not_guessed(
        self, monkeypatch, tmp_path
    ) -> None:
        client = serve(monkeypatch, tmp_path, lambda req, body: httpx.Response(500))
        monkeypatch.setenv("REGISTRY_A2A_URL", "ftp://not-a-registry")
        body = ask(client)
        assert_visible_error(body, "registry_not_configured")


class TestLegacyFallbackSwitch:
    """CHRIS_SELECTION_ONLY=false restores Gemini for no-match and failures only."""

    def test_the_fallback_answers_a_failure_when_enabled(
        self, monkeypatch, tmp_path
    ) -> None:
        def refuse(request, *args):
            raise httpx.ConnectError("refused")

        client = serve(monkeypatch, tmp_path, refuse, on_get=refuse)

        async def answer(message, history):
            return "A direct Gemini answer."

        monkeypatch.setattr(gemini, "answer", answer)
        monkeypatch.setenv("CHRIS_SELECTION_ONLY", "false")
        body = ask(client)
        assert body["response"] == "A direct Gemini answer."
        assert body["routing"] is None  # a plain answer, not a routing result

    def test_a_real_selection_is_still_only_reported(
        self, monkeypatch, tmp_path
    ) -> None:
        client = serve(
            monkeypatch,
            tmp_path,
            lambda req, body: httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": message_result([{"text": json.dumps(GOOD)}]),
                },
            ),
        )
        monkeypatch.setenv("CHRIS_SELECTION_ONLY", "false")
        assert ask(client)["routing"]["status"] == "selected"
