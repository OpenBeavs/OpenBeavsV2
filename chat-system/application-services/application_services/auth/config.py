"""Authentication configuration, environment guards, and Microsoft OIDC endpoints."""

import logging
import os
from urllib.parse import urlencode, urlparse

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from application_services.config import ConfigError, env_flag, get_database_url, get_env

log = logging.getLogger(__name__)

STATE_COOKIE_NAME = "openbeavs_auth_state"

_CLOUD_RUN_MARKERS = ("K_SERVICE", "K_REVISION", "K_CONFIGURATION")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DEV_FALLBACK_SECRET = "openbeavs-dev-fallback-secret-key-change-in-production"
_PLACEHOLDER_SECRETS = {
    _DEV_FALLBACK_SECRET,
    "change-this-in-production-to-a-secure-32-byte-secret",
}
_MIN_PROD_SECRET_BYTES = 32


def _hosts(value: str) -> list[str]:
    """Split a libpq host list ("a,b") into lower-cased names without brackets."""
    return [h.strip().strip("[]").rstrip(".").lower() for h in value.split(",")]


def dev_auth_blocked_reason() -> str | None:
    """Return why development auth shortcuts must not be used here, or None locally.

    Local dev bypasses trust forgeable headers/cookies and fallback secrets, so they are
    permitted only outside Cloud Run and against SQLite or a PostgreSQL server explicitly
    running on this machine.
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


class AuthConfig:
    """OIDC and internal token configuration."""

    @classmethod
    def client_id(cls) -> str:
        return get_env("MICROSOFT_CLIENT_ID", "")

    @classmethod
    def client_secret(cls) -> str:
        return get_env("MICROSOFT_CLIENT_SECRET", "")

    @classmethod
    def tenant_id(cls) -> str:
        return get_env("MICROSOFT_CLIENT_TENANT_ID", "")

    @classmethod
    def redirect_uri(cls) -> str:
        return get_env(
            "MICROSOFT_REDIRECT_URI", "http://localhost:5173/auth/callback"
        )

    @classmethod
    def frontend_origin(cls) -> str:
        """Return the trusted frontend origin for window.postMessage security.

        Defaults to FRONTEND_ORIGIN if set, or derives the origin from
        MICROSOFT_REDIRECT_URI, falling back to 'http://localhost:5173'.
        """
        configured = get_env("FRONTEND_ORIGIN", "")
        if configured:
            return configured.rstrip("/")
        redirect = cls.redirect_uri()
        if redirect:
            parsed = urlparse(redirect)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        return "http://localhost:5173"

    @classmethod
    def cookie_secure(cls) -> bool:
        """Use Secure cookies on Cloud Run or when the frontend origin uses HTTPS."""
        return bool(get_env("K_SERVICE")) or cls.frontend_origin().startswith("https://")

    @classmethod
    def scope(cls) -> str:
        return get_env("MICROSOFT_OAUTH_SCOPE", "openid email profile")

    @classmethod
    def session_secret_key(cls) -> str:
        """Return the JWT signing secret, refusing missing/placeholder values in deployments."""
        secret = get_env("AUTH_SECRET_KEY", "") or get_env("SESSION_SECRET_KEY", "")
        blocked = dev_auth_blocked_reason()
        if blocked is not None:
            if not secret:
                raise ConfigError(f"AUTH_SECRET_KEY is not set ({blocked}).")
            if (
                secret in _PLACEHOLDER_SECRETS
                or len(secret.encode("utf-8")) < _MIN_PROD_SECRET_BYTES
            ):
                raise ConfigError(
                    "AUTH_SECRET_KEY must be a non-placeholder secret of at least 32 bytes."
                )
            return secret
        return secret or _DEV_FALLBACK_SECRET

    @classmethod
    def is_dev_bypass_enabled(cls) -> bool:
        """Allow mock dev logins only when enabled AND running in a local environment."""
        return env_flag("AUTH_BYPASS_DEV") and dev_auth_blocked_reason() is None

    @classmethod
    def is_ms_configured(cls) -> bool:
        return bool(cls.client_id() and cls.tenant_id())

    @classmethod
    def session_token_ttl_seconds(cls) -> int:
        return 7 * 24 * 3600  # 7 days

    @classmethod
    def step_up_ttl_seconds(cls) -> int:
        return 1800  # 30 minutes for privileged tier elevation

    @classmethod
    def get_ms_authorize_url(
        cls, state: str, redirect_uri: str | None = None
    ) -> str | None:
        """Construct Microsoft Entra ID authorize URL."""
        if not cls.is_ms_configured():
            return None
        target_redirect = redirect_uri or cls.redirect_uri()
        params = urlencode(
            {
                "client_id": cls.client_id(),
                "response_type": "code",
                "redirect_uri": target_redirect,
                "scope": cls.scope(),
                "state": state,
                "prompt": "select_account",
            }
        )
        return f"https://login.microsoftonline.com/{cls.tenant_id()}/oauth2/v2.0/authorize?{params}"

    @classmethod
    def get_ms_token_url(cls) -> str:
        """Microsoft OIDC token exchange endpoint."""
        return f"https://login.microsoftonline.com/{cls.tenant_id()}/oauth2/v2.0/token"

    @classmethod
    def get_ms_jwks_url(cls) -> str:
        """Microsoft Entra ID JWKS public keys discovery endpoint."""
        return f"https://login.microsoftonline.com/{cls.tenant_id()}/discovery/v2.0/keys"


def check_auth_config() -> None:
    """Fail startup if dev bypass or an unsafe signing secret is used in deployment."""
    reason = dev_auth_blocked_reason()
    if env_flag("AUTH_BYPASS_DEV"):
        if reason:
            raise RuntimeError(
                f"AUTH_BYPASS_DEV is enabled but {reason}. Development auth bypass "
                "is for local development only; unset it."
            )
        log.warning(
            "AUTH_BYPASS_DEV is ON: mock dev login endpoints and headers are enabled."
        )
    if reason:
        try:
            AuthConfig.session_secret_key()
        except ConfigError as exc:
            raise RuntimeError(str(exc)) from exc
