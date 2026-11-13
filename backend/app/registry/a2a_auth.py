"""Who may call the registry's A2A endpoint.

Production callers (Chris) authenticate with a short-lived **Google-issued ID
token** for an allowed service account. Nothing static is generated or rotated
by hand: the caller's runtime fetches fresh tokens from the metadata server.

The check is done here, in the application, rather than relying only on Cloud Run
IAM, because (a) Cloud Run IAM protects a whole service, not one route, and (b) it
keeps working if the registry is later deployed as a separate service. Limitation:
the caller's identity is its service account, so everything running as an allowed
account is treated as the same caller.

Modes (``REGISTRY_A2A_AUTH``):

- ``google``: verify the bearer token's signature, expiry and audience, require a
  verified email, and require that email to be in ``REGISTRY_A2A_ALLOWED_CALLERS``.
  The audience is ``REGISTRY_A2A_AUDIENCE`` or the registry's public URL.
- ``dev``: no authentication. Only honored in a local environment (the same
  rules as ``REGISTRY_DEV_AUTH``); anywhere else every request is refused.
- unset: ``dev`` in a local environment, ``google`` otherwise.

Anything misconfigured fails closed (HTTP 503), never open.
"""

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_env
from app.registry.auth import dev_auth_blocked_reason

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024
_CACHE_LIMIT = 256
_CACHE_SECONDS = 300


@dataclass(frozen=True)
class Caller:
    """An authenticated caller."""

    identity: str


class AuthError(Exception):
    """Raised by a verifier to refuse a request."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# Takes the bearer token (or None) and returns the caller or raises AuthError.
Verifier = Callable[[str | None], Awaitable[Caller]]


async def open_verifier(token: str | None) -> Caller:
    """Local development only: accept everyone."""
    return Caller(identity="local-development")


def deny_all(reason: str) -> Verifier:
    """A verifier that refuses everything because the configuration is unusable."""

    async def verify(token: str | None) -> Caller:
        log.error("Registry A2A refused a request: %s", reason)
        raise AuthError(503, "The registry's A2A authentication is not configured.")

    return verify


def _split_emails(raw: str) -> set[str]:
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


class GoogleTokenVerifier:
    """Verify a Google ID token and authorize its service account."""

    def __init__(
        self,
        audience: str,
        allowed_callers: set[str],
        verify_token: Callable[[str, str], dict] | None = None,
    ) -> None:
        self._audience = audience
        self._allowed = allowed_callers
        self._verify_token = verify_token or self._google_verify
        self._cache: dict[str, tuple[Caller, float]] = {}

    @staticmethod
    def _google_verify(token: str, audience: str) -> dict:
        # Imported here so the rest of the registry never needs google-auth.
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        return id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=audience
        )

    async def __call__(self, token: str | None) -> Caller:
        if not token:
            raise AuthError(401, "A bearer token is required.")

        key = hashlib.sha256(token.encode()).hexdigest()
        cached = self._cache.get(key)
        if cached and cached[1] > time.time():
            return cached[0]

        try:
            claims = await asyncio.to_thread(self._verify_token, token, self._audience)
        except Exception as e:
            log.info("Rejected a bearer token: %s", type(e).__name__)
            raise AuthError(401, "The bearer token is invalid or expired.") from e

        email = str(claims.get("email", "")).strip().lower()
        if claims.get("email_verified") is not True or not email:
            raise AuthError(401, "The bearer token has no verified email.")
        if email not in self._allowed:
            log.warning("Rejected an unauthorized caller: %s", email)
            raise AuthError(403, "This caller is not allowed to use the registry.")

        caller = Caller(identity=email)
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        expires = min(float(claims.get("exp", 0)), time.time() + _CACHE_SECONDS)
        self._cache[key] = (caller, expires)
        return caller


def _resolve_auth(public_base_url: str) -> tuple[Verifier | None, str | None]:
    """Read the auth settings: ``(verifier, None)``, or ``(None, why it is unusable)``.

    The reason names variables only, never their values.
    """
    blocked = dev_auth_blocked_reason()
    mode = get_env("REGISTRY_A2A_AUTH").lower() or (
        "dev" if blocked is None else "google"
    )

    if mode == "dev":
        if blocked is not None:
            return None, f"unauthenticated mode is not allowed here: {blocked}"
        return open_verifier, None
    if mode == "google":
        allowed = _split_emails(get_env("REGISTRY_A2A_ALLOWED_CALLERS"))
        if not allowed:
            return None, "REGISTRY_A2A_ALLOWED_CALLERS is not set"
        audience = get_env("REGISTRY_A2A_AUDIENCE") or public_base_url
        return GoogleTokenVerifier(audience=audience, allowed_callers=allowed), None
    return None, f"unknown REGISTRY_A2A_AUTH value {mode!r}"


def auth_config_problem(public_base_url: str) -> str | None:
    """Why the A2A endpoint would refuse every request, or None if auth is usable."""
    return _resolve_auth(public_base_url)[1]


def build_verifier(public_base_url: str) -> Verifier:
    """Choose a verifier from the environment (see the module docstring)."""
    verifier, problem = _resolve_auth(public_base_url)
    if verifier is None:
        return deny_all(problem or "unusable configuration")
    if verifier is open_verifier:
        log.warning("Registry A2A authentication is OFF (local development).")
    return verifier


class _TooLarge(Exception):
    """The request body went over the limit."""


class A2AAuthMiddleware:
    """Authenticate every request except the public discovery card, and cap bodies."""

    def __init__(
        self, app: ASGIApp, verifier: Verifier, max_body_bytes: int = MAX_BODY_BYTES
    ) -> None:
        self.app = app
        self.verifier = verifier
        self.max_body_bytes = max_body_bytes

    @staticmethod
    def _is_public(scope: Scope) -> bool:
        """Only fetching the Agent Card is open, so clients can discover the agent."""
        path = scope.get("path", "")
        root = scope.get("root_path", "")
        if root and path.startswith(root):
            path = path[len(root) :]
        return scope["method"] == "GET" and path.startswith("/.well-known/")

    @staticmethod
    def _bearer(scope: Scope) -> str | None:
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                scheme, _, token = value.decode("latin-1").partition(" ")
                if scheme.lower() == "bearer" and token.strip():
                    return token.strip()
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self._is_public(scope):
            try:
                await self.verifier(self._bearer(scope))
            except AuthError as e:
                headers = (
                    {"WWW-Authenticate": "Bearer"} if e.status_code == 401 else None
                )
                response = JSONResponse(
                    {"detail": e.detail}, status_code=e.status_code, headers=headers
                )
                await response(scope, receive, send)
                return

        declared = dict(scope.get("headers", [])).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_body_bytes:
            await JSONResponse({"detail": "Request body too large."}, 413)(
                scope, receive, send
            )
            return

        received = 0
        started = False

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _TooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except _TooLarge:
            if not started:
                await JSONResponse({"detail": "Request body too large."}, 413)(
                    scope, receive, send
                )
