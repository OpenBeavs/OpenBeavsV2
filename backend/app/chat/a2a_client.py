"""Call the configured Chris agent through A2A 1.0 JSON-RPC.

The destination is operator configuration, never a user-supplied agent URL.
Each turn uses a fresh A2A context and replays authorized history in metadata;
the chat database remains the source of conversation history.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError
from a2a.helpers import get_data_parts
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Message,
    Part,
    Role,
    SendMessageRequest,
    TaskState,
)
from a2a.utils.errors import A2AError as SdkError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.chat.schemas import RoutingInfo
from app.config import ConfigError, get_env
from app.history import bounded_history

log = logging.getLogger(__name__)

# Chat -> Chris deadline. Chris spends up to REGISTRY_A2A_TIMEOUT_SECONDS (14 s) on the
# registry plus up to 15 s for optional Gemini fallback. The 35 s default leaves
# response overhead before the browser's 90 s deadline. When expert dispatch is added this
# must grow by the expert-call budget.
DEFAULT_TIMEOUT_SECONDS = 35.0
MAX_TIMEOUT_SECONDS = 120.0
DEFAULT_CHRIS_A2A_URL = "http://127.0.0.1:8000/chris/a2a/"


def timeout_seconds() -> float:
    """The overall Chris deadline from ``CHRIS_A2A_TIMEOUT_SECONDS`` (or the default)."""
    raw = get_env("CHRIS_A2A_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if 1 <= value <= MAX_TIMEOUT_SECONDS else DEFAULT_TIMEOUT_SECONDS


class ChrisUnavailable(RuntimeError):
    """Chris could not produce a completed text reply; safe to show to callers."""


class _Payload(BaseModel):
    """Chris's data part (``openbeavs.chris.routing.v1``), checked field by field."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_: Literal["openbeavs.chris.routing.v1"] = Field(alias="schema")
    status: Literal["selected", "no_match"]
    agent: dict | None = None


@dataclass(frozen=True)
class ChrisReply:
    """Chris's reply: readable text, plus the structured routing decision if sent."""

    text: str
    routing: RoutingInfo | None = None


def parse_routing(data: object) -> RoutingInfo:
    """Validate Chris's routing data part.

    Raises:
        ChrisUnavailable: If it is malformed or contradicts itself, so a broken Chris
            is shown as a failure rather than as a plausible-looking routing result.
    """
    try:
        payload = _Payload.model_validate(data)
        fields = payload.model_dump(exclude={"schema_"})
        agent = fields["agent"]
        if agent is not None:
            # Chris forwards only the agent's id. Chat looks up the display name later
            # (service.py); until then the id stands in for it.
            if (
                set(agent) != {"id"}
                or not isinstance(agent["id"], str)
                or not agent["id"]
            ):
                raise ValueError("agent must be exactly {'id': <text>}")
            fields["agent"] = {"id": agent["id"], "name": agent["id"]}
        info = RoutingInfo.model_validate(fields)
    except (ValidationError, ValueError):
        # Never echo the rejected values.
        log.warning("Chris sent a routing result that is not valid.")
        raise ChrisUnavailable("Chris sent an invalid routing result.") from None
    consistent = (
        (info.status == "selected" and info.agent)
        or (info.status == "no_match" and not info.agent)
    )
    if not consistent:
        log.warning("Chris sent an inconsistent routing result.")
        raise ChrisUnavailable("Chris sent an inconsistent routing result.")
    return info


def _http_client() -> httpx.AsyncClient:
    """Create a scoped client without redirects or environment proxy routing."""
    return httpx.AsyncClient(
        timeout=timeout_seconds(), follow_redirects=False, trust_env=False
    )


async def send_message(message: str, history: list[dict[str, str]]) -> ChrisReply:
    """Send a turn and history to Chris, rejecting failed or unfinished tasks.

    There is no task polling or automatic retry. The reply's text and (when present and
    valid) its structured routing data part are returned; task history and error
    details stay private. History travels in ``metadata.history`` (Chris's contract).
    """
    endpoint = get_env("CHRIS_A2A_URL", DEFAULT_CHRIS_A2A_URL)
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError("CHRIS_A2A_URL must be an http(s) endpoint URL.")

    # The first-party endpoint has a known binding; discovery is not needed to
    # call it. Keep the configured destination rather than following card URLs.
    card = AgentCard(
        name="chris",
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(
                url=endpoint, protocol_binding="JSONRPC", protocol_version="1.0"
            )
        ],
    )
    request = SendMessageRequest(
        message=Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text=message)],
        ),
    )
    request.metadata.update({"history": bounded_history(history)})
    try:
        async with asyncio.timeout(timeout_seconds()), _http_client() as http:
            client = ClientFactory(
                ClientConfig(httpx_client=http, streaming=False)
            ).create(card)
            try:
                async for response in client.send_message(request):
                    if response.HasField("message"):
                        parts = response.message.parts
                    elif response.HasField("task"):
                        if response.task.status.state != TaskState.TASK_STATE_COMPLETED:
                            raise ChrisUnavailable(
                                "Chris did not complete the request."
                            )
                        parts = [
                            part
                            for artifact in response.task.artifacts
                            for part in artifact.parts
                        ]
                    else:
                        raise ChrisUnavailable("Chris returned an unexpected reply.")
                    text = "\n".join(
                        part.text
                        for part in parts
                        if part.WhichOneof("content") == "text" and part.text.strip()
                    )
                    if not text:
                        raise ChrisUnavailable("Chris returned an empty reply.")
                    data = get_data_parts(parts)
                    if len(data) > 1:
                        raise ChrisUnavailable("Chris sent several data parts.")
                    return ChrisReply(
                        text=text, routing=parse_routing(data[0]) if data else None
                    )
            finally:
                await client.close()
    except (httpx.HTTPError, A2AClientError, SdkError, TimeoutError, ValueError):
        raise ChrisUnavailable("Chris is temporarily unavailable.") from None
    raise ChrisUnavailable("Chris returned no reply.")
