"""Pydantic schemas for authentication, SSO, and authorized operations."""

from typing import Literal

from pydantic import BaseModel, Field

AgentStatus = Literal["pending", "approved", "provisional", "revoked"]
ReviewAction = Literal["approve", "provisional", "revoke", "reject"]


class UserProfile(BaseModel):
    """Public authenticated user profile."""

    id: str = Field(..., description="OSU ONID username or subject claim")
    email: str = Field(..., description="Official @oregonstate.edu email")
    display_name: str | None = Field(None, description="Full name from SSO profile")
    role: str = Field("student", description="Role: student, staff, faculty, admin")
    trust_tier: Literal["public", "authenticated", "privileged"] = "authenticated"
    elevated_until: int | None = Field(
        None, description="Epoch timestamp until which Duo MFA elevation is active"
    )


class TokenResponse(BaseModel):
    """Session bearer token response for client authentication."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile


class AuthorizeResponse(BaseModel):
    """Response containing Microsoft authorization URL."""

    authorize_url: str | None
    state: str
    dev_bypass: bool = False


class StepUpInitiateResponse(BaseModel):
    """Response to start Duo MFA step-up re-authentication."""

    authorize_url: str | None
    state: str


class StepUpStatusResponse(BaseModel):
    """Status of user's active Duo MFA elevation."""

    is_elevated: bool
    elevated_until: int | None


class DevLoginRequest(BaseModel):
    """Mock login request body for local dev testing."""

    email: str = Field("benny.beaver@oregonstate.edu", description="Mock OSU email")
    display_name: str | None = Field("Benny Beaver", description="Mock display name")
    role: str = Field("student", description="Mock role (student, staff, faculty, admin)")


class AgentAuthReview(BaseModel):
    """Review metadata for agent approval/revocation under auth rules."""

    status: AgentStatus = Field("pending", description="Review state: pending, approved, provisional, or revoked")
    reviewed_by: str | None = Field(None, description="Email of who approved or revoked it; auto-approvals are system:auto")
    reviewed_at: int | None = Field(None, description="When that decision was made, as a Unix timestamp")
    review_note: str | None = Field(None, description="Reason for decision or automatic warning")


class AgentAuthSubmission(BaseModel):
    """Submission metadata linking an agent to the authenticated submitter."""

    card_url: str = Field(..., max_length=512, description="Unique URL to hosted /.well-known/agent.json card")
    submitted_by: str = Field(..., description="Email of whoever submitted the agent; empty for seeded agents")
