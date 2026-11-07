"""Call the configured Chris agent through A2A 1.0 JSON-RPC.

The destination is operator configuration, never a user-supplied agent URL.
Each turn uses a fresh A2A context and replays authorized history in metadata;
the chat database remains the source of conversation history.
"""

import asyncio
import uuid
from urllib.parse import urlsplit

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError
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

from app.config import ConfigError, get_env

TIMEOUT_SECONDS = 30
DEFAULT_CHRIS_A2A_URL = "http://127.0.0.1:8000/chris/a2a/"


class ChrisUnavailable(RuntimeError):
    """Chris could not produce a completed text reply; safe to show to callers."""


def _http_client() -> httpx.AsyncClient:
    """Create a scoped client without redirects or environment proxy routing."""
    return httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
    )


async def send_message(message: str, history: list[dict[str, str]]) -> str:
    """Send a turn and history to Chris, rejecting failed or unfinished tasks.

    There is no Gemini fallback, task polling, or automatic retry. Only the
    current reply's text is returned; task history and error details stay private.
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
    request.metadata.update({"history": history})
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS), _http_client() as http:
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
                    if text:
                        return text
                    raise ChrisUnavailable("Chris returned an empty reply.")
            finally:
                await client.close()
    except (httpx.HTTPError, A2AClientError, SdkError, TimeoutError, ValueError):
        raise ChrisUnavailable("Chris is temporarily unavailable.") from None
    raise ChrisUnavailable("Chris returned no reply.")
