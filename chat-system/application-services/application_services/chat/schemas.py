"""Frontend chat request and response schemas; existing wire names are preserved."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application_services.history import MAX_QUESTION_BYTES


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
    chat_id: str | None = Field(default=None, max_length=36)
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
    for attribution and is null for a direct Gemini answer. ``chat_id`` is the saved
    session UUID for signed-in callers and null for stateless guest turns.
    The older flat routing fields mirror a *selected* result for frontend compatibility
    and are null otherwise.
    """

    response: str
    chat_id: str | None = None
    routed_to: str | None = None
    agent_name: str | None = None
    routing_confidence: float | None = None
    routing_reason: str | None = None
    routing: RoutingInfo | None = None


class ChatSummary(BaseModel):
    """Metadata for one saved conversation owned by the signed-in user."""

    id: str
    title: str
    agent_id: str | None = None
    source_domain: str | None = None
    is_pinned: bool = False
    created_at: int
    updated_at: int


class ChatMessageOut(BaseModel):
    """One persisted turn returned when loading a saved conversation."""

    id: str
    role: Literal["user", "assistant"]
    content: str
    routed_to: str | None = None
    agent_name: str | None = None
    routing: RoutingInfo | None = None
    created_at: int


class ChatDetail(ChatSummary):
    """Full saved conversation with chronological message turns."""

    messages: list[ChatMessageOut]


class ChatUpdateForm(BaseModel):
    """Request body for PATCH /chat/chats/{chat_id}."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=255)
    is_pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        """Normalize whitespace and reject empty chat titles."""
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Chat title cannot be empty.")
        return cleaned[:255]
