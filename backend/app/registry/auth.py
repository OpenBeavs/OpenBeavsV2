"""Who is calling the registry, and are they an admin?

v2 has no authentication yet (SSO is the "Phase 4" item in the database plan).
Until it exists the registry needs *some* answer to "who is this", so this module
is the single seam: replace ``current_principal`` with verification of the OSU
Microsoft SSO token and nothing else in the registry has to change.

Until then:
- ``REGISTRY_DEV_AUTH=true`` reads the caller from the ``X-User-Id`` and
  ``X-User-Email`` headers. These are trivially forged, so this switch must never
  be set outside local development and tests.
- The switch is refused (routes answer 501) when the process looks like a
  deployment: Cloud Run sets ``K_SERVICE``/``K_REVISION``/``K_CONFIGURATION``, and
  a ``DATABASE_URL`` that is not SQLite or localhost means shared data. The app
  also refuses to start in that combination.
- With the switch off (the default) every protected route answers 501, so a
  deployment without real authentication fails closed.
- ``REGISTRY_ADMIN_EMAILS`` is a comma-separated list of admin emails.
"""

import logging
import os
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.config import env_flag, get_database_url, get_env

log = logging.getLogger(__name__)

# Set by Cloud Run itself, so an operator cannot forget them.
_CLOUD_RUN_MARKERS = ("K_SERVICE", "K_REVISION", "K_CONFIGURATION")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


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


def _hosts(value: str) -> list[str]:
    """Split a libpq host list ("a,b") into lower-cased names without brackets."""
    return [h.strip().strip("[]").rstrip(".").lower() for h in value.split(",")]


def dev_auth_blocked_reason() -> str | None:
    """Return why development auth must not be used here, or None if it is safe.

    Development auth trusts forgeable headers, so it is only allowed when the
    process is not on Cloud Run and the database is local SQLite or a Postgres
    server that is explicitly on this machine. For Postgres the *effective*
    connection target counts: libpq lets ``?host=``, ``?hostaddr=`` or a service
    file override the host in the URL, and a comma-separated list means several
    servers, so every one of them must be local.
    """
    for marker in _CLOUD_RUN_MARKERS:
        if os.environ.get(marker):
            return f"a Cloud Run environment variable ({marker}) is set"
    try:
        url = make_url(get_database_url())
    except ArgumentError:
        return "DATABASE_URL could not be parsed"
    if url.get_backend_name() == "sqlite":
        return None

    query = {key.lower(): value for key, value in url.query.items()}
    if "service" in query:
        return "DATABASE_URL uses a connection service file"
    # Check every place a host can come from, not just the one libpq would pick:
    # a remote name next to a local override is still a misconfiguration.
    targets = _hosts(url.host) if url.host else []
    for key in ("host", "hostaddr"):
        raw = query.get(key)
        if raw is None:
            continue
        for value in (raw,) if isinstance(raw, str) else raw:
            targets += _hosts(value)
    if not targets or any(host not in _LOCAL_HOSTS for host in targets):
        return "DATABASE_URL points at a non-local database"
    return None


def check_dev_auth_config() -> None:
    """Fail startup if development auth is enabled somewhere it is not allowed.

    Raises:
        RuntimeError: ``REGISTRY_DEV_AUTH`` is on in a deployment-like environment.
    """
    if not env_flag("REGISTRY_DEV_AUTH"):
        return
    reason = dev_auth_blocked_reason()
    if reason:
        raise RuntimeError(
            f"REGISTRY_DEV_AUTH is enabled but {reason}. Development auth trusts "
            "forgeable headers and is for local development only; unset it."
        )
    log.warning("REGISTRY_DEV_AUTH is ON: registry callers are trusted from headers.")


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
    reason = dev_auth_blocked_reason()
    if reason:
        log.error("Refusing REGISTRY_DEV_AUTH: %s.", reason)
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
