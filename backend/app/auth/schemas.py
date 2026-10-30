"""Pydantic schemas for authentication and SSO."""

from typing import Literal
from pydantic import BaseModel, EmailStr, Field


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
