"""Chris's registry selection request, sent through the official A2A SDK."""

import asyncio
import json
import uuid
from urllib.parse import urlsplit

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState
from a2a.utils.errors import A2AError

from app.config import ConfigError, get_env

DEFAULT_REGISTRY_A2A_URL = "http://127.0.0.1:8001/"
TIMEOUT_SECONDS = 5


class RegistryUnavailable(RuntimeError):
    """The registry did not provide a completed text response."""


def _http_client() -> httpx.AsyncClient:
    """Configure transport for the operator-configured registry service."""
    return httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
    )


def _validate_selection(text: str) -> None:
    """Accept only a selected agent's id/endpoint or the explicit 'none' sentinel."""
    result = json.loads(text)
    if not isinstance(result, dict) or set(result) != {"agent"}:
        raise ValueError("Invalid registry selection.")
    agent = result["agent"]
    if agent == "none":
        return
    if (
        not isinstance(agent, dict)
        or set(agent) != {"id", "endpoint_url"}
        or not all(isinstance(value, str) and value.strip() for value in agent.values())
    ):
        raise ValueError("Invalid registry selection.")


async def select_agent(message: str, history: list[dict[str, str]]) -> str:
    """Discover the configured registry and relay its selection text unchanged.

    The registry URL is operator configuration, never supplied by a chat caller.
    The SDK owns card discovery and JSON-RPC serialization. History in metadata
    is an application contract, not an A2A standard field. The registry owns its
    selection instructions. No retry, specialist call, or model fallback happens here.
    """
    endpoint = get_env("REGISTRY_A2A_URL", DEFAULT_REGISTRY_A2A_URL)
    try:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        _ = parsed.port
    except ValueError:
        raise ConfigError("REGISTRY_A2A_URL must be an http(s) base URL.") from None

    request = SendMessageRequest(
        message=Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text=message)],
        )
    )
    request.metadata.update({"history": history})
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS), _http_client() as http:
            client = await ClientFactory(
                ClientConfig(httpx_client=http, streaming=False)
            ).create_from_url(endpoint)
            try:
                async for reply in client.send_message(request):
                    if reply.HasField("message"):
                        parts = reply.message.parts
                    elif (
                        reply.HasField("task")
                        and reply.task.status.state == TaskState.TASK_STATE_COMPLETED
                    ):
                        parts = [p for a in reply.task.artifacts for p in a.parts]
                    else:
                        raise RegistryUnavailable(
                            "Registry did not complete selection."
                        )
                    text = "\n".join(
                        p.text
                        for p in parts
                        if p.WhichOneof("content") == "text" and p.text.strip()
                    )
                    if text:
                        _validate_selection(text)
                        return text
                    raise RegistryUnavailable("Registry returned no selection text.")
            finally:
                await client.close()
    except (httpx.HTTPError, A2AClientError, A2AError, TimeoutError, ValueError):
        raise RegistryUnavailable(
            "Registry agent is temporarily unavailable."
        ) from None
    raise RegistryUnavailable("Registry returned no reply.")
