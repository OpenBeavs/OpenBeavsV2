"""Minimal Chris agent for verifying inbound A2A without external services."""

from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

ACKNOWLEDGMENT = "Chris received your message."


class ChrisAgent(BaseAgent):
    """Acknowledge text messages without models, storage, or delegation."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """Return a final acknowledgment; reject requests without usable text."""
        parts = ctx.user_content.parts if ctx.user_content else []
        if not any(part.text and part.text.strip() for part in parts or []):
            raise ValueError("Message must contain non-empty text.")
        yield Event(
            author=self.name,
            content=types.Content(
                role="model", parts=[types.Part(text=ACKNOWLEDGMENT)]
            ),
        )


chris_agent = ChrisAgent(
    name="chris",
    description="Receives a text message and returns a fixed acknowledgment.",
)
