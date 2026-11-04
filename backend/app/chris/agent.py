"""Chris always asks the registry over A2A and relays its selection text."""

import logging
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from app.chris import registry_client
from app.config import ConfigError

log = logging.getLogger(__name__)


class ChrisAgent(BaseAgent):
    """Run the mandatory registry step without model-directed orchestration."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """Call the registry once for every valid message; failures fail the task."""
        parts = ctx.user_content.parts if ctx.user_content else []
        message = "\n".join(p.text for p in parts or [] if p.text).strip()
        if not message:
            raise ValueError("Message must contain non-empty text.")
        metadata = (ctx.run_config.custom_metadata or {}).get("a2a_metadata", {})
        raw_history = metadata.get("history", []) if isinstance(metadata, dict) else []
        history = (
            [
                {"role": turn["role"], "content": turn["content"]}
                for turn in raw_history
                if isinstance(turn, dict)
                and turn.get("role") in ("user", "assistant")
                and isinstance(turn.get("content"), str)
            ]
            if isinstance(raw_history, list)
            else []
        )
        try:
            reply = await registry_client.select_agent(message, history)
        except (ConfigError, registry_client.RegistryUnavailable):
            log.warning("Chris could not obtain a registry selection.")
            raise RuntimeError(
                "Registry selection is unavailable. Please try again."
            ) from None
        yield Event(
            author=self.name,
            content=types.Content(role="model", parts=[types.Part(text=reply)]),
        )


chris_agent = ChrisAgent(
    name="chris",
    description="Asks the registry to select an agent and returns its selection.",
)
