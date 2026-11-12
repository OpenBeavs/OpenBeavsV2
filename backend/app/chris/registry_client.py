"""Chris's registry selection request, sent through the official A2A SDK.

Chris asks the registry which expert fits a question and gets back a
``RoutingResult`` (see ``routing.py``). The registry's reply is one text part holding
compact JSON, ``{"agent": {"id", "endpoint_url"}}`` or ``{"agent": "none"}``, and nothing
else. A registry that cannot select answers with an A2A/JSON-RPC *error* whose message is
a short code (``routing.REGISTRY_ERRORS``); it is reported with that code and
``source = "registry"``.

The question goes in a text part and the earlier turns in a *data part*
``{"history": [...]}``, which is the registry's documented request contract. (The
registry also tolerates ``metadata.history``, but only when no data part has a
history; Chris uses the data part.)

Failures are returned, not hidden: every way the registry call can fail becomes an
``error`` result with a specific code, so the caller (and the user interface) can see
that the registry path was used and why it did not produce a selection:

=========================  =====================================================
``registry_not_configured``  ``REGISTRY_A2A_URL`` is missing or not an http(s) URL
``registry_timeout``         discovery plus selection did not finish in time
``registry_unreachable``     could not connect to the registry
``registry_auth_rejected``   the registry answered 401 or 403
``registry_protocol_error``  an A2A/JSON-RPC level error or non-completed reply
``registry_invalid_reply``   the reply did not match the documented contract
(registry-reported)          a code from ``routing.REGISTRY_ERRORS``, source ``registry``
=========================  =====================================================

Authentication: this module sends **no credential**. That is correct only for the
registry's local-development mode (``REGISTRY_A2A_AUTH=dev``, loopback only); attaching
a Google identity token for a deployed registry is separate, unfinished work.

No retry happens here, and no expert is called.
"""

import asyncio
import logging
import uuid
from urllib.parse import urlsplit

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.client.errors import (
    A2AClientError,
    A2AClientTimeoutError,
    AgentCardResolutionError,
)
from a2a.helpers import get_text_parts, new_data_part, new_message, new_text_part
from a2a.types import Role, SendMessageRequest, TaskState
from a2a.utils.errors import A2AError

from app.chris import routing
from app.config import ConfigError, get_env
from app.history import bounded_history

log = logging.getLogger(__name__)

DEFAULT_REGISTRY_A2A_URL = "http://127.0.0.1:8001/a2a/registry"
# Covers card discovery AND selection. It must exceed the registry's own worst case
# (queue wait + model timeout, 2 s + 8 s in the local setup, plus database time) so a
# slow-but-working registry is not abandoned, yet stay under Chat's deadline.
DEFAULT_TIMEOUT_SECONDS = 14.0
MAX_TIMEOUT_SECONDS = 60.0


def timeout_seconds() -> float:
    """The overall registry deadline from ``REGISTRY_A2A_TIMEOUT_SECONDS`` (or default)."""
    raw = get_env("REGISTRY_A2A_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if 1 <= value <= MAX_TIMEOUT_SECONDS else DEFAULT_TIMEOUT_SECONDS


def _http_client(timeout: float) -> httpx.AsyncClient:
    """Configure transport for the operator-configured registry service."""
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)


def _registry_url() -> str:
    """The registry's base A2A URL (operator configuration, never from a chat caller).

    Raises:
        ConfigError: If it is not an http(s) URL without credentials, query or fragment.
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
    return endpoint


def _causes(error: BaseException) -> list[BaseException]:
    """The error and the errors it was raised from (the SDK wraps httpx errors)."""
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain and len(chain) < 6:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _status_code(error: BaseException) -> int | None:
    """The HTTP status carried by an SDK or httpx error, if any."""
    code = getattr(error, "status_code", None)
    if code is None and isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
    return code if isinstance(code, int) else None


def _registry_reported(chain: list[BaseException]) -> routing.RoutingResult | None:
    """The registry's own failure code, if the error is one of its coded A2A errors.

    The SDK client re-raises a JSON-RPC error as the matching A2A error class
    (``InternalError``, ``InvalidParamsError``) whose ``message`` is the code.
    """
    for error in chain:
        if isinstance(error, A2AError) and not isinstance(error, A2AClientError):
            found = routing.registry_error(error.message)
            if found is not None:
                return found
    return None


def _classify(error: BaseException) -> routing.RoutingResult:
    """Map a transport or protocol failure to a coded error. Logs the type only."""
    chain = _causes(error)
    reported = _registry_reported(chain)
    if reported is not None:
        log.warning("The registry reported a failure: %s", reported.error_code)
        return reported
    log.warning("Registry call failed: %s", type(error).__name__)
    if any(
        isinstance(e, TimeoutError | httpx.TimeoutException | A2AClientTimeoutError)
        for e in chain
    ):
        return routing.chris_error("registry_timeout", retryable=True)
    if any(_status_code(e) in (401, 403) for e in chain):
        return routing.chris_error("registry_auth_rejected", retryable=False)
    if any(
        isinstance(e, httpx.TransportError | AgentCardResolutionError) for e in chain
    ):
        return routing.chris_error("registry_unreachable", retryable=True)
    return routing.chris_error("registry_protocol_error", retryable=True)


def _read_reply(reply) -> routing.RoutingResult:
    """Extract the selection from one SDK response (its text part holds the JSON)."""
    if reply.HasField("message"):
        parts = list(reply.message.parts)
    elif (
        reply.HasField("task")
        and reply.task.status.state == TaskState.TASK_STATE_COMPLETED
    ):
        parts = [p for artifact in reply.task.artifacts for p in artifact.parts]
    else:
        raise A2AError("The registry did not complete selection.")
    texts = [t for t in get_text_parts(parts) if t.strip()]
    if len(texts) != 1:
        raise routing.InvalidRegistryReply("Expected exactly one text part.")
    return routing.parse_registry_text(texts[0])


async def select_agent(
    message: str, history: list[dict[str, str]]
) -> routing.RoutingResult:
    """Ask the registry to select an expert for ``message``.

    Never raises for registry-side problems; they come back as an ``error`` result
    (see the module docstring). The whole exchange, card discovery included, shares one
    deadline (``REGISTRY_A2A_TIMEOUT_SECONDS``).
    """
    try:
        endpoint = _registry_url()
    except ConfigError:
        log.error("REGISTRY_A2A_URL is not a valid http(s) base URL.")
        return routing.chris_error("registry_not_configured", retryable=False)

    request = SendMessageRequest(
        message=new_message(
            parts=[new_text_part(message), new_data_part({"history": bounded_history(history)})],
            role=Role.ROLE_USER,
        )
    )
    request.message.message_id = str(uuid.uuid4())
    deadline = timeout_seconds()
    try:
        async with asyncio.timeout(deadline), _http_client(deadline) as http:
            client = await ClientFactory(
                ClientConfig(httpx_client=http, streaming=False)
            ).create_from_url(endpoint)
            try:
                async for reply in client.send_message(request):
                    return _read_reply(reply)
            finally:
                await client.close()
    except routing.InvalidRegistryReply:
        log.warning("The registry reply did not match its contract.")
        return routing.chris_error("registry_invalid_reply", retryable=False)
    except (httpx.HTTPError, A2AClientError, A2AError, TimeoutError) as error:
        return _classify(error)
    log.warning("The registry returned no reply.")
    return routing.chris_error("registry_protocol_error", retryable=True)
