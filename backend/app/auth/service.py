"""Authentication service operations: user sync and Microsoft token exchange."""

import logging
import time
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.auth.config import AuthConfig
from app.models.user import User

log = logging.getLogger(__name__)


def upsert_user(
    db: Session,
    email: str,
    onid: str | None = None,
    display_name: str | None = None,
    role: str = "student",
) -> User:
    """Find or create an authenticated user record originating from SSO claims."""
    email_clean = email.strip().lower()
    user_id = onid or email_clean.split("@")[0]
    now = int(time.time())

    # Try matching existing user by email or ID
    user = (
        db.query(User)
        .filter((User.email == email_clean) | (User.id == user_id))
        .first()
    )

    if user:
        user.last_login_at = now
        if display_name and not user.display_name:
            user.display_name = display_name
        db.commit()
        db.refresh(user)
        return user

    # Create new student / user record
    new_user = User(
        id=user_id,
        email=email_clean,
        display_name=display_name,
        role=role,
        created_at=now,
        last_login_at=now,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    log.info("Provisioned new SSO user: %s (%s)", user_id, email_clean)
    return new_user


async def exchange_microsoft_code(
    code: str, redirect_uri: str | None = None
) -> dict[str, Any]:
    """Exchange an OAuth authorization code with Microsoft for tokens.

    Raises:
        ValueError: If token exchange fails.
    """
    if not AuthConfig.is_ms_configured():
        raise ValueError("Microsoft Entra ID is not configured.")

    token_url = AuthConfig.get_ms_token_url()
    target_redirect = redirect_uri or AuthConfig.redirect_uri()

    data = {
        "client_id": AuthConfig.client_id(),
        "client_secret": AuthConfig.client_secret(),
        "code": code,
        "redirect_uri": target_redirect,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(token_url, data=data)
        if resp.status_code != 200:
            log.error("Microsoft token exchange failed: %s - %s", resp.status_code, resp.text)
            raise ValueError(f"Microsoft token exchange failed ({resp.status_code}).")
        return resp.json()

