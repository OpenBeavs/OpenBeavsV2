"""Cryptographic token creation, verification, and JWKS validation."""

import logging
import time
from typing import Any

import jwt
from jwt import PyJWKClient, PyJWTError

from app.auth.config import AuthConfig

log = logging.getLogger(__name__)

_jwk_client: PyJWKClient | None = None


def get_jwk_client() -> PyJWKClient:
    """Retrieve or initialize cached PyJWKClient for Microsoft Entra ID."""
    global _jwk_client
    if _jwk_client is None:
        jwks_url = AuthConfig.get_ms_jwks_url()
        _jwk_client = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
    return _jwk_client


def create_session_token(
    user_id: str,
    email: str,
    role: str = "student",
    display_name: str | None = None,
    elevated_until: int | None = None,
    expires_in_seconds: int | None = None,
) -> str:
    """Create a signed HS256 internal session token for OpenBeavs."""
    now = int(time.time())
    ttl = expires_in_seconds or AuthConfig.session_token_ttl_seconds()
    payload = {
        "sub": user_id,
        "email": email.lower(),
        "role": role,
        "name": display_name,
        "elevated_until": elevated_until,
        "iat": now,
        "exp": now + ttl,
        "iss": "openbeavs",
    }
    return jwt.encode(
        payload,
        AuthConfig.session_secret_key(),
        algorithm="HS256",
    )


def decode_session_token(token: str) -> dict[str, Any] | None:
    """Validate and decode an internal session token signed by OpenBeavs.

    Returns the payload dictionary if valid, or None if expired or invalid.
    """
    try:
        return jwt.decode(
            token,
            AuthConfig.session_secret_key(),
            algorithms=["HS256"],
            issuer="openbeavs",
            options={"require": ["sub", "email", "exp"]},
        )
    except PyJWTError as e:
        log.debug("Session token validation failed: %s", e)
        return None


def verify_microsoft_id_token(id_token: str) -> dict[str, Any]:
    """Cryptographically verify a Microsoft Entra ID token using public JWKS keys.

    Raises:
        ValueError: If token signature, claims, or domain check fails.
    """
    if not AuthConfig.is_ms_configured():
        raise ValueError("Microsoft Entra ID is not configured on this server.")

    try:
        client = get_jwk_client()
        signing_key = client.get_signing_key_from_jwt(id_token)
        expected_issuer = f"https://login.microsoftonline.com/{AuthConfig.tenant_id()}/v2.0"

        payload = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=AuthConfig.client_id(),
            issuer=expected_issuer,
            options={"verify_exp": True},
        )
    except Exception as e:
        log.warning("Microsoft ID token verification failed: %s", e)
        raise ValueError(f"Invalid Microsoft token: {e}") from e

    # Extract verified identity
    email = payload.get("email") or payload.get("preferred_username") or ""
    email = email.strip().lower()
    if not email:
        raise ValueError("Token missing email claim.")

    # Enforce institutional boundary
    if not (email.endswith("@oregonstate.edu") or email.endswith(".oregonstate.edu")):
        raise ValueError("Only @oregonstate.edu institutional accounts are permitted.")

    return payload


def create_state_token(user_id: str | None = None, purpose: str = "login") -> str:
    """Create a short-lived (5 min) anti-CSRF state token for the OAuth dance."""
    now = int(time.time())
    payload = {
        "purpose": purpose,
        "user_id": user_id,
        "iat": now,
        "exp": now + 300,
    }
    return jwt.encode(
        payload,
        AuthConfig.session_secret_key(),
        algorithm="HS256",
    )


def verify_state_token(state: str, expected_purpose: str = "login") -> dict[str, Any] | None:
    """Verify an anti-CSRF state token."""
    try:
        payload = jwt.decode(
            state,
            AuthConfig.session_secret_key(),
            algorithms=["HS256"],
            options={"verify_exp": True},
        )
        if payload.get("purpose") != expected_purpose:
            return None
        return payload
    except PyJWTError:
        return None

