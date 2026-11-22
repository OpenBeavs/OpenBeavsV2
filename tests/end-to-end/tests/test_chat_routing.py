"""What the real Conversation Agent emits, as Chat's routing validation accepts it.

Chris's serializer and Application Services' parser run together here, so it is an
end-to-end test. Chat's own validation tests are in Application Services' package.
"""

from application_services.chat.a2a_client import parse_routing
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

    def test_chris_output_is_accepted_by_chat(self) -> None:
        for result in (
            routing.RoutingResult(status="no_match"),
            self.SELECTED,
        ):
            assert (
                parse_routing(routing.to_chat_payload(result)).status == result.status
            )
