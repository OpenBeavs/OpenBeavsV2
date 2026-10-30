"""Authentication endpoints: login, callback, user profile, step-up MFA, and dev bypass."""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth.config import AuthConfig
from app.auth.dependencies import get_current_user
from app.auth.schemas import (
    AuthorizeResponse,
    DevLoginRequest,
    StepUpInitiateResponse,
    StepUpStatusResponse,
    TokenResponse,
    UserProfile,
)
from app.auth.service import exchange_microsoft_code, upsert_user
from app.auth.verifier import (
    create_session_token,
    create_state_token,
    verify_microsoft_id_token,
    verify_state_token,
)
from app.db.session import get_db
from app.models.user import User

log = logging.getLogger(__name__)

router = APIRouter()


def _auth_popup_response(token: str, user_dict: dict, is_elevated: bool = False) -> HTMLResponse:
    """Return minimal HTML page communicating token to opener window and closing popup."""
    html = f"""<!DOCTYPE html>
<html>
<head><title>OpenBeavs Authentication</title></head>
<body>
<div style="font-family: sans-serif; text-align: center; margin-top: 20%;">
  <h3>Authentication successful. Closing window...</h3>
</div>
<script>
  try {{
    const payload = {{
      type: "OPENBEAVS_AUTH_SUCCESS",
      token: "{token}",
      user: {user_dict},
      is_elevated: {"true" if is_elevated else "false"}
    }};
    if (window.opener) {{
      window.opener.postMessage(payload, "*");
    }}
    localStorage.setItem("openbeavs_token", "{token}");
  }} catch (e) {{
    console.error(e);
  }}
  setTimeout(() => window.close(), 600);
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


def _auth_error_response(message: str) -> HTMLResponse:
    """Return error HTML page for OAuth failures."""
    html = f"""<!DOCTYPE html>
<html>
<head><title>Authentication Failed</title></head>
<body style="font-family: sans-serif; text-align: center; margin-top: 15%;">
  <h2 style="color: #c53030;">Authentication Error</h2>
  <p>{message}</p>
  <button onclick="window.close()" style="padding: 8px 16px; margin-top: 16px;">Close</button>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=400)


@router.get("/authorize", response_model=AuthorizeResponse)
async def get_authorization_url(redirect_uri: str | None = None) -> AuthorizeResponse:
    """Generate the Microsoft SSO authorization URL and state token."""
    state = create_state_token(purpose="login")
    authorize_url = AuthConfig.get_ms_authorize_url(state, redirect_uri=redirect_uri)
    return AuthorizeResponse(
        authorize_url=authorize_url,
        state=state,
        dev_bypass=AuthConfig.is_dev_bypass_enabled(),
    )


@router.get("/callback")
async def oauth_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str = Query("", description="OAuth authorization code"),
    state: str = Query("", description="State parameter"),
    error: str = Query("", description="Error message from provider"),
) -> HTMLResponse:
    """Handle the OAuth redirect callback from Microsoft Entra ID."""
    if error:
        log.warning("OAuth error reported from Microsoft: %s", error)
        return _auth_error_response(f"Microsoft OAuth Error: {error}")

    if not code or not state:
        return _auth_error_response("Missing authorization code or state parameter.")

    # Verify anti-CSRF state token
    state_payload = verify_state_token(state, expected_purpose="login")
    if not state_payload:
        return _auth_error_response("Invalid or expired session state token.")

    # Exchange code for Microsoft token response
    try:
        token_data = await exchange_microsoft_code(code)
    except ValueError as e:
        return _auth_error_response(str(e))

    id_token = token_data.get("id_token")
    if not id_token:
        return _auth_error_response("Microsoft did not return an id_token.")

    # Validate Microsoft claims against JWKS
    try:
        claims = verify_microsoft_id_token(id_token)
    except ValueError as e:
        return _auth_error_response(str(e))

    email = claims.get("email") or claims.get("preferred_username") or ""
    display_name = claims.get("name")
    onid = email.split("@")[0]

    # Upsert user record
    user = upsert_user(
        db,
        email=email,
        onid=onid,
        display_name=display_name,
        role="student",
    )

    # Issue internal session token
    session_token = create_session_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        display_name=user.display_name,
    )

    user_info = {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
    }
    return _auth_popup_response(session_token, user_info)


@router.get("/me", response_model=UserProfile)
async def get_current_user_profile(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> UserProfile:
    """Return the profile and privileges of the current authenticated user."""
    elevated_until = getattr(request.state, "elevated_until", None)
    now = int(time.time())
    is_elevated = bool(elevated_until and elevated_until > now)

    tier = "privileged" if is_elevated else "authenticated"

    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        trust_tier=tier,
        elevated_until=elevated_until if is_elevated else None,
    )


@router.post("/step-up/initiate", response_model=StepUpInitiateResponse)
async def initiate_step_up(
    user: Annotated[User, Depends(get_current_user)],
) -> StepUpInitiateResponse:
    """Initiate Duo MFA step-up re-authentication for privileged agent access."""
    state = create_state_token(user_id=user.id, purpose="stepup")
    authorize_url = AuthConfig.get_ms_authorize_url(state)
    if not authorize_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft OAuth is not configured on this server.",
        )
    return StepUpInitiateResponse(authorize_url=authorize_url, state=state)


@router.get("/step-up/callback")
async def step_up_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str = Query("", description="OAuth authorization code"),
    state: str = Query("", description="State parameter"),
    error: str = Query("", description="Error message from provider"),
) -> HTMLResponse:
    """Handle Microsoft redirect after step-up re-authentication."""
    if error:
        return _auth_error_response(f"Step-up OAuth Error: {error}")

    state_payload = verify_state_token(state, expected_purpose="stepup")
    if not state_payload or not state_payload.get("user_id"):
        return _auth_error_response("Invalid or expired step-up state token.")

    user_id = state_payload["user_id"]
    user = db.get(User, user_id)
    if not user:
        return _auth_error_response("User session not found.")

    try:
        token_data = await exchange_microsoft_code(code)
        id_token = token_data.get("id_token")
        if not id_token:
            return _auth_error_response("No id_token in response.")
        claims = verify_microsoft_id_token(id_token)
    except ValueError as e:
        return _auth_error_response(str(e))

    reauth_email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    if reauth_email != user.email.lower():
        return _auth_error_response("Re-authenticated account does not match the active session.")

    # Issue elevated session token valid for 30 minutes
    elevated_until = int(time.time()) + AuthConfig.step_up_ttl_seconds()
    elevated_token = create_session_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        display_name=user.display_name,
        elevated_until=elevated_until,
    )

    user_info = {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
    }
    return _auth_popup_response(elevated_token, user_info, is_elevated=True)


# =========================================================================
# Local Developer Mock Endpoints (active ONLY when AUTH_BYPASS_DEV=true)
# =========================================================================


@router.post("/dev/login", response_model=TokenResponse)
async def dev_login(
    req: DevLoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """Fast mock login for local development and UI testing without Azure AD."""
    if not AuthConfig.is_dev_bypass_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev login is disabled in this environment.",
        )

    email = req.email.strip().lower()
    onid = email.split("@")[0]
    user = upsert_user(
        db,
        email=email,
        onid=onid,
        display_name=req.display_name,
        role=req.role,
    )

    token = create_session_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        display_name=user.display_name,
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=AuthConfig.session_token_ttl_seconds(),
        user=UserProfile(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            trust_tier="authenticated",
            elevated_until=None,
        ),
    )


@router.post("/dev/elevate", response_model=TokenResponse)
async def dev_elevate(
    user: Annotated[User, Depends(get_current_user)],
) -> TokenResponse:
    """Elevate the current dev user session to privileged Duo MFA tier."""
    if not AuthConfig.is_dev_bypass_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev elevation is disabled in this environment.",
        )

    elevated_until = int(time.time()) + AuthConfig.step_up_ttl_seconds()
    elevated_token = create_session_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        display_name=user.display_name,
        elevated_until=elevated_until,
    )

    return TokenResponse(
        access_token=elevated_token,
        token_type="bearer",
        expires_in=AuthConfig.session_token_ttl_seconds(),
        user=UserProfile(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            trust_tier="privileged",
            elevated_until=elevated_until,
        ),
    )

