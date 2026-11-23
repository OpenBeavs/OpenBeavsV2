"""Chat's validation of Chris's structured routing result (openbeavs.chris.routing.v1).

The test that feeds it what the real Chris emits is an end-to-end test, kept with the
tests that cross systems.
"""

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from application_services.chat.a2a_client import (
    ChrisUnavailable,
    parse_routing,
    send_message,
)

GOOD = {
    "schema": "openbeavs.chris.routing.v1",
    "status": "selected",
    "agent": {"id": "math", "name": "Math Expert", "description": "Arithmetic."},
}
ERROR = {
    "code": "registry_timeout",
    "retryable": True,
    "source": "chris",
}


class TestParseRouting:
    def test_selected_carries_the_id_name_and_description(self) -> None:
        info = parse_routing(GOOD)
        assert info.status == "selected"
        assert (info.agent.id, info.agent.name, info.agent.description) == (
            "math",
            "Math Expert",
            "Arithmetic.",
        )
        assert info.confidence is None and info.reason is None

    @pytest.mark.parametrize("name", ["", "   "])
    def test_a_blank_name_is_accepted(self, name: str) -> None:
        """A selected expert whose registered name is blank is still a selection."""
        info = parse_routing({**GOOD, "agent": {**GOOD["agent"], "name": name}})
        assert info.status == "selected"
        assert (info.agent.id, info.agent.name) == ("math", name)

    def test_a_null_description_is_accepted(self) -> None:
        agent = {**GOOD["agent"], "description": None}
        info = parse_routing({**GOOD, "agent": agent})
        assert info.agent.name == "Math Expert" and info.agent.description is None

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
            {**GOOD, "agent": {"id": "math", "name": "Math"}},  # no description key
            {**GOOD, "agent": {**GOOD["agent"], "id": ""}},
            {**GOOD, "agent": {**GOOD["agent"], "id": 7}},
            {**GOOD, "agent": {}},
            {**GOOD, "agent": {"id": "math"}},  # the id alone is no longer enough
            {**GOOD, "agent": {**GOOD["agent"], "name": 7}},
            {**GOOD, "agent": {**GOOD["agent"], "description": 7}},
            {**GOOD, "agent": {**GOOD["agent"], "endpoint_url": "https://x.test"}},
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
            "application_services.chat.a2a_client._http_client",
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
