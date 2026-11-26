"""Authentication endpoints: login, callback, user profile, step-up MFA, and dev bypass."""

import html
import json
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from application_services.auth.config import STATE_COOKIE_NAME, AuthConfig
from application_services.auth.dependencies import get_current_user
from application_services.auth.schemas import (
    AuthorizeResponse,
    DevLoginRequest,
    StepUpInitiateResponse,
    TokenResponse,
    UserProfile,
)
from application_services.auth.service import exchange_microsoft_code, upsert_user
from application_services.auth.verifier import (
    create_session_token,
    create_state_token,
    verify_microsoft_id_token,
    verify_state_token,
)
from application_services.database.session import get_db
from application_services.models.user import User

log = logging.getLogger(__name__)

router = APIRouter()


def _auth_popup_response(
    token: str,
    user_dict: dict,
    is_elevated: bool = False,
    target_origin: str | None = None,
) -> HTMLResponse:
    """Return HTML page communicating token to opener window or redirecting to home."""
    name = user_dict.get("display_name") or user_dict.get("email") or "OSU User"
    safe_name = html.escape(str(name))
    safe_user_json = json.dumps(user_dict)
    origin = target_origin or AuthConfig.frontend_origin()
    safe_origin_json = json.dumps(origin)
    page_html = f"""<!DOCTYPE html>
<html>
<head>
  <title>OpenBeavs - Signed In</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align: center; margin-top: 15%; background: #fdfdfd; color: #1a1a1a;">
  <div style="max-width: 420px; margin: 0 auto; padding: 24px; border: 1px solid #e5e5e5; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
    <div style="font-size: 40px; margin-bottom: 12px;">🦫</div>
    <h2 style="color: #d73f09; margin: 0 0 8px 0;">Signed In Successfully</h2>
    <p style="margin: 0 0 16px 0; color: #4a4a4a;">Welcome, <strong>{safe_name}</strong>!</p>
    <a href="/" style="display: inline-block; padding: 10px 24px; background: #d73f09; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 14px;">Continue to OpenBeavs</a>
  </div>
<script>
  try {{
    const payload = {{
      type: "OPENBEAVS_AUTH_SUCCESS",
      token: "{token}",
      user: {safe_user_json},
      is_elevated: {"true" if is_elevated else "false"}
    }};
    if (window.opener) {{
      window.opener.postMessage(payload, {safe_origin_json});
      setTimeout(() => window.close(), 600);
    }} else {{
      setTimeout(() => {{ window.location.href = "/"; }}, 1000);
    }}
    localStorage.setItem("openbeavs_token", "{token}");
  }} catch (e) {{
    console.error(e);
  }}
</script>
</body>
</html>"""
    response = HTMLResponse(content=page_html)
    response.set_cookie(
        key="openbeavs_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=AuthConfig.cookie_secure(),
        max_age=7 * 24 * 3600,
        path="/",
    )
    return response


def _auth_error_response(message: str) -> HTMLResponse:
    """Return error HTML page for OAuth failures with HTML-escaped message."""
    safe_message = html.escape(message)
    page_html = f"""<!DOCTYPE html>
<html>
<head><title>Authentication Failed</title></head>
<body style="font-family: sans-serif; text-align: center; margin-top: 15%;">
  <h2 style="color: #c53030;">Authentication Error</h2>
  <p>{safe_message}</p>
  <button onclick="window.close()" style="padding: 8px 16px; margin-top: 16px;">Close</button>
</body>
</html>"""
    return HTMLResponse(content=page_html, status_code=400)


@router.get("/authorize", response_model=AuthorizeResponse)
async def get_authorization_url(
    response: Response, redirect_uri: str | None = None
) -> AuthorizeResponse:
    """Generate the Microsoft SSO authorization URL and state token."""
    state = create_state_token(purpose="login")
    response.set_cookie(
        key=STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        samesite="lax",
        secure=AuthConfig.cookie_secure(),
        max_age=300,
        path="/",
    )
    authorize_url = AuthConfig.get_ms_authorize_url(state, redirect_uri=redirect_uri)
    return AuthorizeResponse(
        authorize_url=authorize_url,
        state=state,
        dev_bypass=AuthConfig.is_dev_bypass_enabled(),
    )


@router.get("/login")
async def login_redirect(redirect_uri: str | None = None) -> RedirectResponse:
    """Redirect directly to the Microsoft Entra ID sign-in page."""
    state = create_state_token(purpose="login")
    authorize_url = AuthConfig.get_ms_authorize_url(state, redirect_uri=redirect_uri)
    if not authorize_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft SSO is not configured.",
        )
    response = RedirectResponse(url=authorize_url)
    response.set_cookie(
        key=STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        samesite="lax",
        secure=AuthConfig.cookie_secure(),
        max_age=300,
        path="/",
    )
    return response


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
        err_resp = _auth_error_response(f"Microsoft OAuth Error: {error}")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    if not code or not state:
        err_resp = _auth_error_response("Missing authorization code or state parameter.")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    # 1. Enforce browser session binding against login CSRF
    cookie_state = request.cookies.get(STATE_COOKIE_NAME)
    if not cookie_state or cookie_state != state:
        log.warning("OAuth callback rejected: state does not match browser session cookie.")
        err_resp = _auth_error_response("Invalid or expired session state token.")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    # 2. Verify anti-CSRF state token and enforce single-use
    state_payload = verify_state_token(state, expected_purpose="login", single_use=True)
    if not state_payload:
        err_resp = _auth_error_response("Invalid or expired session state token.")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    # Exchange code for Microsoft token response
    try:
        token_data = await exchange_microsoft_code(code)
    except ValueError as e:
        err_resp = _auth_error_response(str(e))
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    id_token = token_data.get("id_token")
    if not id_token:
        err_resp = _auth_error_response("Microsoft did not return an id_token.")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    # Validate Microsoft claims against JWKS
    try:
        claims = verify_microsoft_id_token(id_token)
    except ValueError as e:
        err_resp = _auth_error_response(str(e))
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

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
    popup_resp = _auth_popup_response(session_token, user_info)
    popup_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
    return popup_resp


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


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    """Clear session cookies so the browser ends its signed-in session."""
    secure = AuthConfig.cookie_secure()
    response.delete_cookie(
        key="openbeavs_token",
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )
    response.delete_cookie(
        key="dev_user_email",
        path="/",
        samesite="lax",
        secure=secure,
    )
    return {"status": "ok"}


@router.post("/step-up/initiate", response_model=StepUpInitiateResponse)
async def initiate_step_up(
    response: Response,
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
    response.set_cookie(
        key=STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        samesite="lax",
        secure=AuthConfig.cookie_secure(),
        max_age=300,
        path="/",
    )
    return StepUpInitiateResponse(authorize_url=authorize_url, state=state)


@router.get("/step-up/callback")
async def step_up_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str = Query("", description="OAuth authorization code"),
    state: str = Query("", description="State parameter"),
    error: str = Query("", description="Error message from provider"),
) -> HTMLResponse:
    """Handle Microsoft redirect after step-up re-authentication."""
    if error:
        err_resp = _auth_error_response(f"Step-up OAuth Error: {error}")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    if not code or not state:
        err_resp = _auth_error_response("Missing authorization code or state parameter.")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    # 1. Enforce browser session binding against CSRF
    cookie_state = request.cookies.get(STATE_COOKIE_NAME)
    if not cookie_state or cookie_state != state:
        log.warning("Step-up OAuth rejected: state does not match browser session cookie.")
        err_resp = _auth_error_response("Invalid or expired step-up state token.")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    # 2. Verify anti-CSRF state token and enforce single-use
    state_payload = verify_state_token(state, expected_purpose="stepup", single_use=True)
    if not state_payload or not state_payload.get("user_id"):
        err_resp = _auth_error_response("Invalid or expired step-up state token.")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    user_id = state_payload["user_id"]
    user = db.get(User, user_id)
    if not user:
        err_resp = _auth_error_response("User session not found.")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    try:
        token_data = await exchange_microsoft_code(code)
        id_token = token_data.get("id_token")
        if not id_token:
            err_resp = _auth_error_response("No id_token in response.")
            err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
            return err_resp
        claims = verify_microsoft_id_token(id_token)
    except ValueError as e:
        err_resp = _auth_error_response(str(e))
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

    reauth_email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    if reauth_email != user.email.lower():
        err_resp = _auth_error_response("Re-authenticated account does not match the active session.")
        err_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
        return err_resp

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
    popup_resp = _auth_popup_response(elevated_token, user_info, is_elevated=True)
    popup_resp.delete_cookie(STATE_COOKIE_NAME, path="/")
    return popup_resp


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

