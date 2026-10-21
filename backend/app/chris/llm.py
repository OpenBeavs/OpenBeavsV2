"""Chris's language-model access.

This is the only module that knows which provider is used (currently Gemini,
called directly over its REST Interactions API). The rest of Chris calls ``generate`` and
never sees provider details, so swapping providers means rewriting this file.
"""

import httpx

from app.config import require_env

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
REQUEST_TIMEOUT_SECONDS = 30

# Adapted from the v1 direct-answer prompt. No agents exist in v2 yet, so the
# installed-agents list is always "none" (keeps Chris from inventing agents).
CHRIS_SYSTEM_PROMPT = (
    "You are Chris, the OpenBeavs AI hub assistant. "
    "You are answering the user directly; there is no agent being called right now. "
    "NEVER invent or guess agent names. Only refer to agents that appear in the "
    "INSTALLED AGENTS list below. If the list is empty, say the user has no agents installed."
    "\n\nINSTALLED AGENTS: none"
)


class LLMError(RuntimeError):
    """Raised when the model call fails or returns no usable text."""


def _to_interaction_payload(
    messages: list[dict], model: str, response_schema: dict | None = None
) -> dict:
    """Convert provider-neutral messages into a Gemini Interactions request body.

    Args:
        messages: Dicts with ``role`` ("system", "user" or "assistant") and
            ``content``. System messages are joined into ``system_instruction``.
            A single user message is sent as a plain string (the documented
            form). With earlier turns, ``input`` is a list of steps:
            "user" becomes ``user_input`` and "assistant" becomes ``model_output``.
        model: Gemini model id.
        response_schema: Optional JSON Schema. When set, the model is
            constrained to reply with JSON matching it.
    """
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]

    if len(turns) == 1:
        model_input: str | list[dict] = turns[0]["content"]
    else:
        model_input = [
            {
                "type": "model_output" if m["role"] == "assistant" else "user_input",
                "content": [{"type": "text", "text": m["content"]}],
            }
            for m in turns
        ]

    payload: dict = {"model": model, "input": model_input}
    if system:
        payload["system_instruction"] = system
    if response_schema is not None:
        payload["response_format"] = {
            "type": "text",
            "mime_type": "application/json",
            "schema": response_schema,
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
        raise LLMError("Gemini returned an unexpected response shape.")
    if not text.strip():
        raise LLMError("Gemini returned an empty reply.")
    return text


async def generate(messages: list[dict], response_schema: dict | None = None) -> str:
    """Send chat messages to the model and return its text reply.

    With ``response_schema`` the reply is a JSON string constrained to that
    schema (structured output). Callers must still parse and validate it.

    Raises:
        app.config.ConfigError: If GEMINI_API_KEY or CHRIS_MODEL is missing.
        LLMError: If the request fails or the reply has no text.
    """
    api_key = require_env("GEMINI_API_KEY")
    model = require_env("CHRIS_MODEL").removeprefix("models/")

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            # Key goes in a header, not the URL, so it never lands in logs.
            response = await client.post(
                GEMINI_URL,
                headers={"x-goog-api-key": api_key},
                json=_to_interaction_payload(messages, model, response_schema),
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        # Status code only; the response body is not echoed back.
        raise LLMError(f"Gemini request failed with HTTP {e.response.status_code}.") from e
    except (httpx.HTTPError, ValueError) as e:
        raise LLMError(f"Gemini request failed: {type(e).__name__}.") from e

    return _extract_text(data)
