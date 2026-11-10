"""Gemini answering capability used by Chris when registry selection fails."""

import asyncio

from google import genai
from google.genai import types

from app.config import require_env

TIMEOUT_SECONDS = 15
SYSTEM_INSTRUCTION = (
    "You are Chris, the OpenBeavs assistant for Oregon State University. "
    "Answer the user's question clearly and concisely. Be honest about uncertainty. "
    "Do not claim to have consulted a specialist or accessed private university data."
)


class GeminiUnavailable(RuntimeError):
    """Gemini did not return a usable answer; contains no provider error details."""


async def answer(message: str, history: list[dict[str, str]] | None = None) -> str:
    """Generate a text answer using the supplied conversation history.

    Read GEMINI_API_KEY and CHRIS_MODEL only when called. No provider-side chat
    session is created. Callers supply earlier turns; the current message is
    appended once. Configuration and input errors remain distinct from sanitized
    provider failures. This function does not decide when fallback should occur.
    """
    message = message.strip()
    if not message:
        raise ValueError("Message must contain non-empty text.")
    contents = []
    for turn in history or []:
        if turn["role"] not in ("user", "assistant"):
            raise ValueError("History roles must be user or assistant.")
        contents.append(
            types.Content(
                role="model" if turn["role"] == "assistant" else "user",
                parts=[types.Part(text=turn["content"])],
            )
        )
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

    api_key = require_env("GEMINI_API_KEY")
    model = require_env("CHRIS_MODEL").removeprefix("models/")
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            with genai.Client(
                api_key=api_key,
                vertexai=False,
                http_options=types.HttpOptions(
                    timeout=TIMEOUT_SECONDS * 1000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            ) as client:
                async with client.aio as async_client:
                    response = await async_client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                        ),
                    )
        text = response.text
        if not isinstance(text, str) or not text.strip():
            raise GeminiUnavailable("Gemini returned no answer text.")
        return text.strip()
    except Exception:  # noqa: BLE001 - sanitize all failures at the provider boundary
        # Provider errors can contain credentials, request content, or URLs.
        # Keep those details out of logs and exceptions exposed to A2A callers.
        raise GeminiUnavailable("Gemini is temporarily unavailable.") from None
