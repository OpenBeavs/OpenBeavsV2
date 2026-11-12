"""Chat's validation of Chris's structured routing result (openbeavs.chris.routing.v1)."""

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from app.chat.a2a_client import ChrisUnavailable, parse_routing, send_message
from app.chris import routing

GOOD = {
    "schema": "openbeavs.chris.routing.v1",
    "status": "selected",
    "agent": {"id": "math"},
}
ERROR = {
    "code": "registry_timeout",
    "retryable": True,
    "source": "chris",
}


class TestParseRouting:
    def test_selected_carries_only_the_id_until_chat_looks_the_rest_up(self) -> None:
        info = parse_routing(GOOD)
        assert info.status == "selected"
        assert (info.agent.id, info.agent.name) == ("math", "math")
        assert info.confidence is None and info.reason is None

    def test_no_match(self) -> None:
        info = parse_routing({**GOOD, "status": "no_match", "agent": None})
        assert info.status == "no_match" and info.agent is None

    def test_error_payloads_are_rejected(self) -> None:
        with pytest.raises(ChrisUnavailable):
            parse_routing({**GOOD, "status": "error", "agent": None, "error": ERROR})

    @pytest.mark.parametrize(
        "bad",
        [
            "selected",
            [GOOD],
            {**GOOD, "schema": "something-else"},
            {k: v for k, v in GOOD.items() if k != "schema"},
            {**GOOD, "status": "maybe"},
            {**GOOD, "agent": None},  # selected without an agent
            {**GOOD, "error": ERROR},  # selected with an error
            {**GOOD, "status": "no_match"},  # no_match with an agent
            {**GOOD, "status": "error", "agent": None, "error": None},
            {**GOOD, "status": "error", "error": ERROR},  # error naming an agent
            {**GOOD, "extra": "field"},
            {**GOOD, "confidence": 0.9},  # no longer part of the contract
            {**GOOD, "reason": "Fits."},
            {**GOOD, "agent": {"id": "math", "name": "Math"}},  # id only
            {**GOOD, "agent": {"id": ""}},
            {**GOOD, "agent": {"id": 7}},
            {**GOOD, "agent": {}},
            {
                **GOOD,
                "status": "error",
                "agent": None,
                "error": {**ERROR, "source": "x"},
            },
        ],
    )
    def test_malformed_results_are_rejected_without_echoing_values(self, bad) -> None:
        with pytest.raises(ChrisUnavailable) as raised:
            parse_routing(bad)
        assert "invalid" in str(raised.value) or "inconsistent" in str(raised.value)


class TestChrisSerialization:
    SELECTED = routing.RoutingResult(
        status="selected",
        agent=routing.SelectedAgent(
            id="a", endpoint_url="https://secret.example.test/rpc"
        ),
    )

    def test_only_the_id_is_forwarded_to_chat(self) -> None:
        payload = routing.to_chat_payload(self.SELECTED)
        assert payload["agent"] == {"id": "a"}
        assert "secret.example.test" not in json.dumps(payload)
        assert set(payload) == {"schema", "status", "agent"}

    def test_chris_output_is_accepted_by_chat(self) -> None:
        for result in (
            routing.RoutingResult(status="no_match"),
            self.SELECTED,
        ):
            assert (
                parse_routing(routing.to_chat_payload(result)).status == result.status
            )

    def test_the_summary_never_reads_like_an_answer(self) -> None:
        assert routing.summary_text(self.SELECTED) == "I found a specialist for your question."

    @pytest.mark.parametrize("failure", [routing.chris_error("registry_timeout", True), routing.registry_error("selection_busy")])
    def test_failures_cannot_be_forwarded_as_messages(self, failure) -> None:
        with pytest.raises(ValueError):
            routing.to_chat_payload(failure)
        with pytest.raises(ValueError):
            routing.summary_text(failure)


class TestRegistryContractParsing:
    """The registry's reply text, exactly as Chris reads it."""

    def test_selected(self) -> None:
        result = routing.parse_registry_text(
            '{"agent":{"id":"m","endpoint_url":"https://x.test/rpc"}}'
        )
        assert result.status == "selected"
        assert (result.agent.id, result.agent.endpoint_url) == (
            "m",
            "https://x.test/rpc",
        )

    def test_none(self) -> None:
        assert routing.parse_registry_text('{"agent":"none"}').status == "no_match"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "not json",
            "[]",
            "{}",
            '{"agent": null}',
            '{"agent": "math"}',
            '{"agent": {"id": "m"}}',
            '{"agent": {"id": "m", "endpoint_url": ""}}',
            '{"agent": {"id": " ", "endpoint_url": "https://x.test/rpc"}}',
            '{"agent": {"id": "m", "endpoint_url": "https://x.test/rpc", "name": "M"}}',
            '{"agent": "none", "reason": "x"}',
            '{"status": "selected", "agent": "none"}',
        ],
    )
    def test_anything_else_is_invalid(self, text: str) -> None:
        with pytest.raises(routing.InvalidRegistryReply):
            routing.parse_registry_text(text)

    def test_registry_error_codes_carry_a_retry_rule(self) -> None:
        assert routing.registry_error("selection_busy").retryable is True
        assert routing.registry_error("not_configured").retryable is False
        assert routing.registry_error("selection_busy").source == "registry"
        assert routing.registry_error("made_up_code") is None


def _chris_reply(parts: list[dict]):
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "message": {"messageId": "r", "role": "ROLE_AGENT", "parts": parts}
                },
            },
        )

    return respond


class TestSendMessage:
    def _send(self, parts: list[dict]):
        with patch(
            "app.chat.a2a_client._http_client",
            side_effect=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(_chris_reply(parts))
            ),
        ):
            return asyncio.run(send_message("Hello", []))

    def test_text_and_data_are_both_returned(self) -> None:
        reply = self._send([{"text": "Selected."}, {"data": GOOD}])
        assert reply.text == "Selected." and reply.routing.status == "selected"

    def test_a_plain_text_reply_has_no_routing(self) -> None:
        reply = self._send([{"text": "Just text."}])
        assert reply.text == "Just text." and reply.routing is None

    def test_a_bad_data_part_is_a_failure_not_a_routing_result(self) -> None:
        with pytest.raises(ChrisUnavailable):
            self._send([{"text": "Selected."}, {"data": {**GOOD, "agent": None}}])

    def test_several_data_parts_are_rejected(self) -> None:
        with pytest.raises(ChrisUnavailable):
            self._send([{"text": "x"}, {"data": GOOD}, {"data": GOOD}])

    def test_data_without_text_is_rejected(self) -> None:
        with pytest.raises(ChrisUnavailable):
            self._send([{"data": GOOD}])
