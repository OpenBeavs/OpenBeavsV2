"""Chris's routing results: the registry's reply as he reads it, and what he sends Chat.

The ``openbeavs.chris.routing.v1`` data part is the contract between Chris and Chat;
Chat's validation of it is tested in Application Services.
"""

import json

import pytest

from conversation_agent import routing


class TestChrisSerialization:
    SELECTED = routing.RoutingResult(
        status="selected",
        agent=routing.SelectedAgent(
            id="a",
            endpoint_url="https://secret.example.test/rpc",
            name="Expert A",
            description="Answers A questions.",
        ),
    )

    def test_the_endpoint_is_never_forwarded_to_chat(self) -> None:
        payload = routing.to_chat_payload(self.SELECTED)
        assert payload["agent"] == {
            "id": "a",
            "name": "Expert A",
            "description": "Answers A questions.",
        }
        assert "secret.example.test" not in json.dumps(payload)
        assert set(payload) == {"schema", "status", "agent"}

    @pytest.mark.parametrize("failure", [routing.chris_error("registry_timeout", True), routing.registry_error("selection_busy")])
    def test_failures_cannot_be_forwarded_as_messages(self, failure) -> None:
        with pytest.raises(ValueError):
            routing.to_chat_payload(failure)


class TestRegistryContractParsing:
    """The registry's reply text, exactly as Chris reads it."""

    def test_selected(self) -> None:
        result = routing.parse_registry_text(
            '{"agent":{"id":"m","endpoint_url":"https://x.test/rpc","name":"M","description":"Maths."}}'
        )
        assert result.status == "selected"
        assert result.agent == routing.SelectedAgent(
            id="m",
            endpoint_url="https://x.test/rpc",
            name="M",
            description="Maths.",
        )

    def test_selected_without_a_description(self) -> None:
        result = routing.parse_registry_text(
            '{"agent":{"id":"m","endpoint_url":"https://x.test/rpc","name":"M","description":null}}'
        )
        assert result.status == "selected"
        assert result.agent.name == "M" and result.agent.description is None

    @pytest.mark.parametrize("name", ["", "   "])
    def test_selected_with_a_blank_name(self, name: str) -> None:
        """The registry's record may hold a blank name; the expert is still selected."""
        result = routing.parse_registry_text(
            json.dumps(
                {
                    "agent": {
                        "id": "m",
                        "endpoint_url": "https://x.test/rpc",
                        "name": name,
                        "description": None,
                    }
                }
            )
        )
        assert result.status == "selected"
        assert (result.agent.endpoint_url, result.agent.name) == (
            "https://x.test/rpc",
            name,
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
            '{"agent": {"id": "m", "endpoint_url": "https://x.test/rpc"}}',
            '{"agent": {"id": "m", "endpoint_url": "https://x.test/rpc", "name": "M"}}',
            '{"agent": {"id": "m", "endpoint_url": "", "name": "M", "description": null}}',
            '{"agent": {"id": " ", "endpoint_url": "https://x.test/rpc", "name": "M", "description": null}}',
            '{"agent": {"id": "m", "endpoint_url": "https://x.test/rpc", "name": 5, "description": null}}',
            '{"agent": {"id": "m", "endpoint_url": "https://x.test/rpc", "name": "M", "description": 5}}',
            '{"agent": {"id": "m", "endpoint_url": "https://x.test/rpc", "name": "M", "description": null, "card_url": "https://x.test/card"}}',
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
