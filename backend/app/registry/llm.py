"""Registry-only Gemini access, including per-process concurrency and deadlines.

Uses REGISTRY_MODEL and REGISTRY_GEMINI_API_KEY (or GEMINI_API_KEY), independently
of Chris. Limits apply per process: deployments must also cap workers/instances.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.config import ConfigError, get_env, require_env

log = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT = 8
DEFAULT_WAIT_SECONDS = 2.0
MAX_CONCURRENT_LIMIT = 64
MAX_WAIT_LIMIT = 60.0
LLMCall = Callable[[str, str, dict], Awaitable[str]]

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
REQUEST_TIMEOUT_SECONDS = 8
MAX_TIMEOUT_SECONDS = 60


class ModelBusyError(RuntimeError):
    """No model slot became free within the allowed wait."""


def _read_number(name: str, default: float, low: float, high: float) -> float:
    """Read a number from the environment; bad or out-of-range values use the default."""
    raw = get_env(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not low <= value <= high:  # also false for NaN
        log.warning("%s must be between %g and %g; using %g.", name, low, high, default)
        return default
    return value


class ModelLimiter:
    """Allow a bounded number of model calls at once, with a bounded wait."""

    def __init__(self, max_concurrent: int, wait_seconds: float) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        if wait_seconds < 0:
            raise ValueError("wait_seconds must not be negative")
        self.max_concurrent = max_concurrent
        self.wait_seconds = wait_seconds
        self._semaphore: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def from_env(cls) -> "ModelLimiter":
        """Build the limiter from the environment, using the documented defaults."""
        return cls(
            int(
                _read_number(
                    "REGISTRY_MODEL_MAX_CONCURRENCY",
                    DEFAULT_MAX_CONCURRENT,
                    1,
                    MAX_CONCURRENT_LIMIT,
                )
            ),
            _read_number(
                "REGISTRY_MODEL_QUEUE_SECONDS",
                DEFAULT_WAIT_SECONDS,
                0,
                MAX_WAIT_LIMIT,
            ),
        )

    def _slots(self) -> asyncio.Semaphore:
        """The semaphore for the running event loop (created on first use)."""
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._loop is not loop:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
            self._loop = loop
        return self._semaphore

    def wrap(self, call: LLMCall) -> LLMCall:
        """Return ``call`` guarded by this limiter."""

        async def limited(system: str, user: str, schema: dict) -> str:
            slots = self._slots()
            try:
                # A free slot is taken without waiting (so a wait of 0 still works
                # on every supported Python); otherwise wait, but only so long.
                if slots.locked():
                    await asyncio.wait_for(slots.acquire(), timeout=self.wait_seconds)
                else:
                    await slots.acquire()
            except TimeoutError:
                log.warning(
                    "Model concurrency limit (%d) reached; refusing a request.",
                    self.max_concurrent,
                )
                raise ModelBusyError from None
            try:
                return await call(system, user, schema)
            finally:
                slots.release()

        return limited


def request_timeout() -> float:
    """The bounded overall model deadline, with the same safe fallback as other limits."""
    return _read_number(
        "REGISTRY_MODEL_TIMEOUT_SECONDS",
        REQUEST_TIMEOUT_SECONDS,
        1,
        MAX_TIMEOUT_SECONDS,
    )


class LLMError(RuntimeError):
    """Raised when the model call fails or returns no usable text."""


def _model_name() -> str:
    """Return the configured model id, without a leading ``models/``."""
    name = get_env("REGISTRY_MODEL")
    if not name:
        raise ConfigError("REGISTRY_MODEL is not set. Add it to backend/.env.")
    return name.removeprefix("models/")


def _api_key() -> str:
    """Return the registry's own key, or the generic ``GEMINI_API_KEY``."""
    key = get_env("REGISTRY_GEMINI_API_KEY")
    return key or require_env("GEMINI_API_KEY")


def _payload(system: str, user: str, model: str, schema: dict) -> dict:
    """Build a Gemini Interactions request body that returns schema-shaped JSON."""
    # store=False: do not keep the interaction on Google's servers.
    payload: dict = {"model": model, "input": user, "store": False}
    if system:
        payload["system_instruction"] = system
    payload["response_format"] = {
        "type": "text",
        "mime_type": "application/json",
        "schema": schema,
    }
    return payload


def _extract_text(data: dict) -> str:
    """Return the reply text from an Interaction response, or raise ``LLMError``."""
    try:
        text = "".join(
            item.get("text", "")
            for step in data["steps"]
            if step.get("type") == "model_output"
            for item in step.get("content", [])
            if item.get("type") == "text"
        )
    except (KeyError, TypeError, AttributeError):
        raise LLMError("Gemini returned an unexpected response shape.") from None
    if not text.strip():
        raise LLMError("Gemini returned an empty reply.")
    return text


async def generate_json(
    system: str,
    user: str,
    schema: dict,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Return schema-constrained model text; the caller must still validate it.

    Raises ConfigError for missing configuration and LLMError for request/reply failures.
    """
    api_key = _api_key()
    model = _model_name()
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=request_timeout())
    try:
        async with asyncio.timeout(request_timeout()):
            # The key goes in a header, not the URL, so it never lands in logs.
            response = await http.post(
                GEMINI_URL,
                headers={"x-goog-api-key": api_key},
                json=_payload(system, user, model, schema),
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        # Status code only; the response body is not echoed back.
        raise LLMError(
            f"Gemini request failed with HTTP {e.response.status_code}."
        ) from e
    except (httpx.HTTPError, ValueError, TimeoutError) as e:
        raise LLMError(f"Gemini request failed: {type(e).__name__}.") from e
    finally:
        if owns_client:
            await http.aclose()
    return _extract_text(data)
