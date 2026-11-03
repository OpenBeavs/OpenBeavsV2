"""Frontend chat request and response schemas; existing wire names are preserved."""

from typing import Any, Literal

from pydantic import BaseModel


class HistoryMessage(BaseModel):
    """One earlier turn in the conversation."""

    role: Literal["user", "assistant"]
    content: str


class ChrisMessageForm(BaseModel):
    """Request body for POST /chris/message."""

    message: str
    history: list[HistoryMessage] = []
    chat_id: str | None = None
    user_id: str | None = None
    guest_session_id: str | None = None
    source_domain: str | None = None


class ChrisMessageResponse(BaseModel):
    """Response body.

    ``routed_to`` and ``agent_name`` are set when Chris picked an agent. The
    ``routing_*`` fields show the model's decision (when routing ran), which
    helps tune routing even when the answer came directly from Chris.
    """

    response: str
    chat_id: str | None = None
    routed_to: str | None = None
    agent_name: str | None = None
    routing_confidence: float | None = None
    routing_reason: str | None = None


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
