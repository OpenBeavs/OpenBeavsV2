"""Chris's language-model access.

This is the only module that knows which provider is used (currently Gemini,
called directly over its REST API). The rest of Chris calls ``generate`` and
never sees provider details, so swapping providers means rewriting this file.
"""

import httpx

from app.config import require_env

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
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


def _to_gemini_payload(messages: list[dict], response_schema: dict | None = None) -> dict:
    """Convert provider-neutral messages into a Gemini ``generateContent`` body.

    Args:
        messages: Dicts with ``role`` ("system", "user" or "assistant") and
            ``content``. System messages become Gemini's ``system_instruction``;
            "assistant" is mapped to Gemini's "model" role.
        response_schema: Optional JSON schema (Gemini schema dialect). When set,
            the model is constrained to reply with JSON matching it.
    """
    system_parts = [{"text": m["content"]} for m in messages if m["role"] == "system"]
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
        if m["role"] != "system"
    ]
    payload: dict = {"contents": contents}
    if system_parts:
        payload["system_instruction"] = {"parts": system_parts}
    if response_schema is not None:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        }
    return payload


def _extract_text(data: dict) -> str:
    """Return the reply text from a Gemini response, or raise ``LLMError``."""
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError):
        raise LLMError("Gemini returned no candidates (the request may have been blocked).")
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
    url = f"{GEMINI_BASE_URL}/{model}:generateContent"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            # Key goes in a header, not the URL, so it never lands in logs.
            response = await client.post(
                url,
                headers={"x-goog-api-key": api_key},
                json=_to_gemini_payload(messages, response_schema),
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        # Status code only; the response body is not echoed back.
        raise LLMError(f"Gemini request failed with HTTP {e.response.status_code}.") from e
    except (httpx.HTTPError, ValueError) as e:
        raise LLMError(f"Gemini request failed: {type(e).__name__}.") from e

    return _extract_text(data)
