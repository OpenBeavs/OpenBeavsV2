"""Who is calling the registry, and are they an admin?

v2 has no authentication yet (SSO is the "Phase 4" item in the database plan).
Until it exists the registry needs *some* answer to "who is this", so this module
is the single seam: replace ``current_principal`` with verification of the OSU
Microsoft SSO token and nothing else in the registry has to change.

Until then:
- ``REGISTRY_DEV_AUTH=true`` reads the caller from the ``X-User-Id`` and
  ``X-User-Email`` headers. These are trivially forged, so this switch must never
  be set outside local development and tests.
- With the switch off (the default) every protected route answers 501, so a
  deployment without real authentication fails closed.
- ``REGISTRY_ADMIN_EMAILS`` is a comma-separated list of admin emails.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import env_flag, get_env


@dataclass(frozen=True)
class Principal:
    """The authenticated caller."""

    id: str
    email: str
    is_admin: bool


def _admin_emails() -> set[str]:
    """Return the configured admin emails, lower-cased."""
    raw = get_env("REGISTRY_ADMIN_EMAILS")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def current_principal(
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_email: Annotated[str | None, Header()] = None,
) -> Principal:
    """Return the caller, or raise 401/501.

    Raises:
        HTTPException: 501 when no authentication is configured, 401 when the
            development headers are missing.
    """
    if not env_flag("REGISTRY_DEV_AUTH"):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Authentication is not configured for the registry yet.",
        )
    if not x_user_id or not x_user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Id or X-User-Email header.",
        )
    email = x_user_email.strip().lower()
    return Principal(
        id=x_user_id.strip(), email=email, is_admin=email in _admin_emails()
    )


def require_admin(
    principal: Annotated[Principal, Depends(current_principal)],
) -> Principal:
    """Return the caller if they are an admin, otherwise raise 403."""
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can do this.",
        )
    return principal
