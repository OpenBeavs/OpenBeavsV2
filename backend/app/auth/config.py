"""Authentication configuration settings and endpoints."""

from urllib.parse import urlencode

from app.config import env_flag, get_env


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
    def scope(cls) -> str:
        return get_env("MICROSOFT_OAUTH_SCOPE", "openid email profile")

    @classmethod
    def session_secret_key(cls) -> str:
        # Fallback for dev only; production deployments require setting SESSION_SECRET_KEY
        secret = get_env("SESSION_SECRET_KEY", "")
        if not secret:
            return "openbeavs-dev-fallback-secret-key-change-in-production"
        return secret

    @classmethod
    def is_dev_bypass_enabled(cls) -> bool:
        return env_flag("AUTH_BYPASS_DEV")

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

