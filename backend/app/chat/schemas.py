"""Frontend chat request and response schemas; existing wire names are preserved."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.history import MAX_QUESTION_BYTES


class HistoryMessage(BaseModel):
    """One earlier turn in the conversation."""

    role: Literal["user", "assistant"]
    content: str


class ChrisMessageForm(BaseModel):
    """Request body for POST /chat/message."""

    message: str = Field(max_length=MAX_QUESTION_BYTES)

    @field_validator("message")
    @classmethod
    def question_fits_transport(cls, value: str) -> str:
        """Reject oversized questions before forwarding them to another service."""
        if len(value.encode("utf-8", errors="replace")) > MAX_QUESTION_BYTES:
            raise ValueError("Message must be at most 4,000 UTF-8 bytes.")
        return value
    history: list[HistoryMessage] = []
    source_domain: str | None = None


class RoutedAgent(BaseModel):
    """The expert the registry selected. Endpoints are not exposed to the browser."""

    id: str
    name: str
    description: str | None = None


class RoutingInfo(BaseModel):
    """Chris's routing decision, kept structured for the frontend to display.

    Failures are not routing messages: they use HTTP errors without persistence.
    Chris emits ``selected`` after a successful expert reply. The wire schema
    still accepts ``no_match`` from older Chris instances.
    """

    status: Literal["selected", "no_match"]
    agent: RoutedAgent | None = None
    confidence: float | None = None
    reason: str | None = None


class ChrisMessageResponse(BaseModel):
    """Response body.

    ``response`` is the expert or Gemini answer. ``agent_name`` identifies the expert
    for attribution and is null for a direct Gemini answer.
    The older flat routing fields mirror a *selected* result for frontend compatibility
    and are null otherwise.
    """

    response: str
    # Retained as null for older response consumers; chat is stateless.
    chat_id: None = None
    routed_to: str | None = None
    agent_name: str | None = None
    routing_confidence: float | None = None
    routing_reason: str | None = None
    routing: RoutingInfo | None = None


class AgentSummary(BaseModel):
    """Public summary of an active registered agent."""

    id: str
    name: str
    description: str | None = None
    endpoint_url: str
    card_url: str | None = None
    trust_tier: str
    required_role: str | None = None
    skills: list[Any] | None = None
    capabilities: dict[str, Any] | None = None
    is_featured: bool = False
