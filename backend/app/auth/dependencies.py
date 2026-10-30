"""FastAPI route dependencies for authentication and authorization."""

import time
from typing import Annotated, Callable

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.config import AuthConfig
from app.auth.service import upsert_user
from app.auth.verifier import decode_session_token, verify_microsoft_id_token
from app.db.session import get_db
from app.models.user import User


async def get_optional_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user_email: Annotated[str | None, Header()] = None,
) -> User | None:
    """Extract and verify caller identity from Bearer token or Dev Bypass headers.

    Returns None for unauthenticated (guest) requests.
    """
    token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()

    # 1. Try decoding as OpenBeavs internal session token (fast symmetric verification)
    if token:
        payload = decode_session_token(token)
        if payload:
            user = db.get(User, payload["sub"])
            if user:
                request.state.user = user
                request.state.elevated_until = payload.get("elevated_until")
                return user

        # 2. Try validating as raw Microsoft Entra ID token (asymmetric JWKS verification)
        if AuthConfig.is_ms_configured():
            try:
                ms_claims = verify_microsoft_id_token(token)
                email = ms_claims.get("email") or ms_claims.get("preferred_username") or ""
                onid = email.split("@")[0]
                name = ms_claims.get("name")
                user = upsert_user(db, email=email, onid=onid, display_name=name)
                request.state.user = user
                request.state.elevated_until = None
                return user
            except ValueError:
                # Token provided but invalid
                pass

    # 3. Local Developer Bypass (only when AUTH_BYPASS_DEV=true)
    if AuthConfig.is_dev_bypass_enabled():
        dev_email = x_dev_user_email or request.cookies.get("dev_user_email")
        if dev_email and dev_email.strip():
            dev_user = upsert_user(
                db,
                email=dev_email.strip().lower(),
                display_name="Dev Beav",
                role="student",
            )
            request.state.user = dev_user
            request.state.elevated_until = int(time.time()) + 3600
            return dev_user

    return None


async def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    """Enforce that the caller is authenticated. Fails closed with 401."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in with your OSU ONID.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(allowed_roles: list[str]) -> Callable[[User], User]:
    """Factory dependency to enforce user roles (e.g. staff, faculty, admin)."""

    def role_checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Requires one of roles {allowed_roles}, but caller has role '{user.role}'.",
            )
        return user

    return role_checker


async def require_elevated_user(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Enforce that user has active Duo MFA elevation for the privileged tier."""
    elevated_until = getattr(request.state, "elevated_until", None)
    now = int(time.time())

    if not elevated_until or elevated_until <= now:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Privileged access requires Duo MFA step-up re-authentication.",
        )
    return user

