"""Call a registry-selected RPC endpoint without discovering a different destination.

The registry contract does not include a protocol version. Deployments configure
CHRIS_EXPERT_A2A_VERSION (0.3 by default, or 1.0); the SDK handles the wire format.
Only public HTTPS experts are supported. No caller credentials are forwarded.
"""

import asyncio
import logging
import uuid
from urllib.parse import urlsplit

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError, A2AClientTimeoutError
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
from a2a.utils.errors import A2AError

from app.config import get_env
from app.history import bounded_history
from app.registry.security import UnsafeURLError, validate_agent_url

log = logging.getLogger(__name__)
DEFAULT_TIMEOUT_SECONDS = 30.0


class ExpertUnavailable(RuntimeError):
    """The expert could not return a completed text answer."""


def timeout_seconds() -> float:
    """Bound the complete expert exchange, including destination validation."""
    try:
        value = float(get_env("CHRIS_EXPERT_TIMEOUT_SECONDS", "30"))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if 1 <= value <= 60 else DEFAULT_TIMEOUT_SECONDS


def _http_client(timeout: float) -> httpx.AsyncClient:
    """Do not follow redirects or route requests through environment proxies."""
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)


def _failure_details(error: BaseException) -> tuple[str, int | None, str]:
    """Classify SDK wrappers without including exception messages or URLs."""
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain and len(chain) < 8:
        chain.append(current)
        current = current.__cause__ or current.__context__
    status = next((e.response.status_code for e in chain
                   if isinstance(e, httpx.HTTPStatusError)), None)
    if any(isinstance(e, (TimeoutError, httpx.TimeoutException,
                         A2AClientTimeoutError)) for e in chain):
        code = "expert_timeout"
    elif status in (401, 403):
        code = "expert_auth_rejected"
    elif status is not None:
        code = "expert_http_error"
    elif any(isinstance(e, httpx.TransportError) for e in chain):
        code = "expert_unreachable"
    elif isinstance(error, UnsafeURLError):
        code = "expert_unsafe_url"
    else:
        code = "expert_protocol_error"
    return code, status, type(chain[-1]).__name__


async def send_message(
    endpoint_url: str, message: str, history: list[dict[str, str]]
) -> str:
    """Send once and accept text only from a message or completed task artifacts.

    History uses request metadata, matching Chris's A2A contract. There is no retry,
    task polling, identity forwarding, or fallback that could mask an expert failure.
    URL validation has the same DNS-rebinding limitation as registry registration;
    production egress should also restrict destinations.
    """
    deadline = timeout_seconds()
    try:
        async with asyncio.timeout(deadline):
            if (
                any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in endpoint_url)
                or "\\" in endpoint_url
                or urlsplit(endpoint_url).query
                or "#" in endpoint_url
            ):
                raise ValueError("Invalid expert endpoint.")
            await asyncio.to_thread(validate_agent_url, endpoint_url)
            version = get_env("CHRIS_EXPERT_A2A_VERSION", "0.3")
            if version not in ("1.0", "0.3"):
                raise ValueError("Unsupported expert protocol.")
            card = AgentCard(
                name="expert",
                capabilities=AgentCapabilities(streaming=False),
                supported_interfaces=[AgentInterface(
                    url=endpoint_url, protocol_binding="JSONRPC",
                    protocol_version=version,
                )],
            )
            request = SendMessageRequest(message=Message(
                message_id=str(uuid.uuid4()), role=Role.ROLE_USER,
                parts=[Part(text=message)],
            ))
            request.metadata.update({"history": bounded_history(history)})
            async with _http_client(deadline) as http:
                client = ClientFactory(
                    ClientConfig(httpx_client=http, streaming=False)
                ).create(card)
                try:
                    async for response in client.send_message(request):
                        if response.HasField("message"):
                            parts = response.message.parts
                        elif (
                            response.HasField("task")
                            and response.task.status.state == TaskState.TASK_STATE_COMPLETED
                        ):
                            parts = [p for a in response.task.artifacts for p in a.parts]
                        else:
                            raise ExpertUnavailable("Expert did not complete the request.")
                        answer = "\n".join(
                            p.text for p in parts
                            if p.WhichOneof("content") == "text" and p.text.strip()
                        )
                        if not answer:
                            raise ExpertUnavailable("Expert returned no text.")
                        return answer
                finally:
                    await client.close()
            raise ExpertUnavailable("Expert returned no reply.")
    except (httpx.HTTPError, A2AClientError, A2AError, TimeoutError, ValueError,
            ExpertUnavailable) as error:
        # Never log provider details, response bodies, or endpoint credentials.
        code, status, cause = _failure_details(error)
        log.warning("Expert call failed: code=%s http_status=%s cause=%s",
                    code, status, cause)
        raise ExpertUnavailable("Expert is temporarily unavailable.") from None
