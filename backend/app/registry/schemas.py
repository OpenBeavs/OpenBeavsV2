"""Request and response bodies for the registry API."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TrustTier = Literal["public", "authenticated", "privileged"]
ReviewAction = Literal["approve", "provisional", "revoke", "reject"]


class SubmitAgentForm(BaseModel):
    """Body for submitting an agent.

    Only the URL is accepted. Status, trust tier and every other field are set by
    the server, so a submitter cannot grant their own agent any trust.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=512, description="Agent or card URL")


class ReviewForm(BaseModel):
    """Body for an admin review decision."""

    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    note: str | None = Field(default=None, max_length=2000)
    trust_tier: TrustTier | None = None
    required_role: str | None = Field(default=None, max_length=64)
    is_featured: bool | None = None


class RegistryAgentOut(BaseModel):
    """A registry entry as returned to callers.

    ``submitted_by`` and the review fields are filled in only for admins and for
    the submitter, and are null for everyone else.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    endpoint_url: str
    card_url: str | None = None
    trust_tier: str
    required_role: str | None = None
    skills: list[Any] | None = None
    capabilities: dict[str, Any] | None = None
    is_active: bool
    is_featured: bool
    status: str
    submitted_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: int | None = None
    review_note: str | None = None
    created_at: int
    updated_at: int
