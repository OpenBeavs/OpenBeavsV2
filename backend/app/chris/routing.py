"""Routing results: what the registry decided, as Chris holds and forwards it.

Two contracts meet here.

**Registry -> Chris** (trimmed to what Chris needs): one agent message with a single text
part holding compact JSON, exactly one of::

    {"agent": {"id": "<agent id>", "endpoint_url": "<A2A endpoint>"}}    an expert fits
    {"agent": "none"}                                                  nothing fits

``parse_registry_text`` validates it strictly (exact keys, non-empty strings, no
coercion). Anything else becomes ``registry_invalid_reply``; Chris never guesses what a
malformed reply meant. A registry that cannot select answers with an A2A/JSON-RPC *error*
whose message is a short code (see ``REGISTRY_ERRORS``); ``registry_client`` turns it into
an ``error`` result. The reply carries no name, description, confidence or reason: the
record's id is the key, and anything else is looked up from the database by whoever
needs it (Chat does, for display).

**Chris -> Chat** (``openbeavs.chris.routing.v1``): successful replies contain
selected-agent or diagnostic no-match data. Backend failures are logged and use
A2A failure handling; they are never serialized as chat messages or routing data.
Selected endpoints are never forwarded to Chat.

Nothing here calls an expert. A ``selected`` result is a routing decision, not an answer.
"""

import json
from dataclasses import dataclass
from typing import Any

from google.genai import types

CHRIS_SCHEMA_ID = "openbeavs.chris.routing.v1"

SELECTED = "selected"
NO_MATCH = "no_match"
ERROR = "error"

SOURCE_REGISTRY = "registry"
SOURCE_CHRIS = "chris"

# The failure codes a registry reports (the A2A error message), and whether retrying may
# help. The registry documents the same list; this is the receiving side's copy.
REGISTRY_ERRORS: dict[str, bool] = {
    "invalid_request": False,
    "not_configured": False,
    "selection_unavailable": True,
    "selection_busy": True,
    "invalid_model_reply": True,
    "agent_unavailable": True,
    "registry_capacity_exceeded": False,
    "registry_unavailable": True,
    "internal_error": True,
}

# A2A data parts travel through ADK as a tagged blob (see google.adk.a2a part_converter).
_DATA_START = b"<a2a_datapart_json>"
_DATA_END = b"</a2a_datapart_json>"


class InvalidRegistryReply(ValueError):
    """The registry's reply did not match the documented contract."""


@dataclass(frozen=True)
class SelectedAgent:
    """The expert the registry picked. Chris keeps the endpoint for later dispatch."""

    id: str
    endpoint_url: str


@dataclass(frozen=True)
class RoutingResult:
    """A routing decision: ``selected``, ``no_match`` or ``error``."""

    status: str
    agent: SelectedAgent | None = None
    error_code: str | None = None
    retryable: bool = False
    source: str | None = None  # who reported an error: "registry" or "chris"


def chris_error(code: str, retryable: bool) -> RoutingResult:
    """A failure Chris itself observed while asking the registry."""
    return RoutingResult(
        status=ERROR, error_code=code, retryable=retryable, source=SOURCE_CHRIS
    )


def registry_error(code: str) -> RoutingResult | None:
    """The result for a registry-reported failure code, or None if the code is unknown."""
    if code not in REGISTRY_ERRORS:
        return None
    return RoutingResult(
        status=ERROR,
        error_code=code,
        retryable=REGISTRY_ERRORS[code],
        source=SOURCE_REGISTRY,
    )


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def parse_registry_text(text: str) -> RoutingResult:
    """Validate the registry's reply text and turn it into a ``RoutingResult``.

    Raises:
        InvalidRegistryReply: If it is not exactly one of the two documented shapes.
    """
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        raise InvalidRegistryReply("The registry reply is not JSON.") from None
    if not isinstance(data, dict) or set(data) != {"agent"}:
        raise InvalidRegistryReply("The registry reply is not valid.")
    agent = data["agent"]
    if agent == "none":
        return RoutingResult(status=NO_MATCH)
    if (
        isinstance(agent, dict)
        and set(agent) == {"id", "endpoint_url"}
        and _non_empty_text(agent["id"])
        and _non_empty_text(agent["endpoint_url"])
    ):
        return RoutingResult(
            status=SELECTED,
            agent=SelectedAgent(id=agent["id"], endpoint_url=agent["endpoint_url"]),
        )
    raise InvalidRegistryReply("The registry reply is not valid.")


def to_chat_payload(result: RoutingResult) -> dict[str, Any]:
    """The ``openbeavs.chris.routing.v1`` data part Chris sends to Chat."""
    if result.status not in (SELECTED, NO_MATCH):
        raise ValueError("Failures cannot be serialized as chat replies.")
    return {
        "schema": CHRIS_SCHEMA_ID,
        "status": result.status,
        "agent": {"id": result.agent.id} if result.agent is not None else None,
    }


def summary_text(result: RoutingResult) -> str:
    """One plain sentence for the text part. It states the routing, never an answer."""
    if result.status == SELECTED and result.agent is not None:
        return "I found a specialist for your question."
    if result.status == NO_MATCH:
        return "The registry found no registered expert that fits this question."
    raise ValueError("Failures cannot be summarized as chat replies.")


def to_event_parts(result: RoutingResult) -> list[types.Part]:
    """Parts for Chris's ADK event: the summary text plus the structured data part."""
    blob = _DATA_START + json.dumps(to_chat_payload(result)).encode() + _DATA_END
    return [
        types.Part(text=summary_text(result)),
        types.Part(inline_data=types.Blob(mime_type="text/plain", data=blob)),
    ]
