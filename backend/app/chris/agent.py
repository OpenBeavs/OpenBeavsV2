"""Chris asks the registry first and reports a selected expert.

By default, a no-match or registry failure is answered directly with Gemini,
which needs GEMINI_API_KEY and CHRIS_MODEL. Set CHRIS_SELECTION_ONLY=true to
inspect registry outcomes without fallback. Selected experts are not called yet.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator

from a2a.utils.errors import InternalError
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from app.chris import gemini, registry_client, routing
from app.config import ConfigError, get_env

log = logging.getLogger(__name__)


def selection_only() -> bool:
    """Whether diagnostic selection-only mode is explicitly enabled."""
    return get_env("CHRIS_SELECTION_ONLY", "false").lower() not in ("false", "0", "no")


def _history(ctx: InvocationContext) -> list[dict[str, str]]:
    """Earlier turns from the caller (Chat) in the request metadata, validated."""
    metadata = (ctx.run_config.custom_metadata or {}).get("a2a_metadata", {})
    raw = metadata.get("history", []) if isinstance(metadata, dict) else []
    if not isinstance(raw, list):
        return []
    return [
        {"role": turn["role"], "content": turn["content"]}
        for turn in raw
        if isinstance(turn, dict)
        and turn.get("role") in ("user", "assistant")
        and isinstance(turn.get("content"), str)
    ]


class ChrisAgent(BaseAgent):
    """Run the mandatory registry step without model-directed orchestration."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """Ask the registry once and report its decision."""
        parts = ctx.user_content.parts if ctx.user_content else []
        message = "\n".join(p.text for p in parts or [] if p.text).strip()
        if not message:
            raise ValueError("Message must contain non-empty text.")
        history = _history(ctx)

        result = await registry_client.select_agent(message, history)
        if result.status == routing.ERROR:
            log.warning(
                "Registry selection failed: code=%s source=%s retryable=%s",
                result.error_code, result.source, result.retryable,
            )
            if selection_only():
                raise InternalError("Chris is temporarily unavailable.")
        if result.status != routing.SELECTED and not selection_only():
            answer = await self._gemini_answer(message, history)
            yield Event(
                author=self.name,
                content=types.Content(role="model", parts=[types.Part(text=answer)]),
            )
            return
        log.info("Registry selection: status=%s agent=%s", result.status,
                 result.agent.id if result.agent else None)
        yield Event(
            author=self.name,
            content=types.Content(role="model", parts=routing.to_event_parts(result)),
        )

    @staticmethod
    async def _gemini_answer(message: str, history: list[dict[str, str]]) -> str:
        """The legacy direct answer (only when ``CHRIS_SELECTION_ONLY`` is false)."""
        try:
            async with asyncio.timeout(15):
                return await gemini.answer(message, history)
        except (ConfigError, gemini.GeminiUnavailable, TimeoutError):
            log.warning("Chris could not obtain a Gemini answer.")
            # A failed A2A call lets Chat show a notice without saving a fake answer.
            raise InternalError("Chris is temporarily unavailable.") from None


chris_agent = ChrisAgent(
    name="chris",
    description=(
        "Asks the registry which registered expert fits a question and reports the "
        "selection. It does not call the expert yet."
    ),
)
