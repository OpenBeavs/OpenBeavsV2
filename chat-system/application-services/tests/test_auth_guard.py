"""Deployment guards for AUTH_BYPASS_DEV and AUTH_SECRET_KEY."""

import pytest
from fastapi.testclient import TestClient

from application_services.auth.config import (
    AuthConfig,
    check_auth_config,
    dev_auth_blocked_reason,
)
from application_services.config import ConfigError
from application_services.main import app

CLOUD_RUN_MARKERS = ("K_SERVICE", "K_REVISION", "K_CONFIGURATION")
VALID_PROD_SECRET = "a-real-32-byte-production-signing-secret-value"


@pytest.fixture(autouse=True)
def clean_local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test from a local SQLite environment without Cloud Run variables."""
    for marker in CLOUD_RUN_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./local.db")
    monkeypatch.delenv("AUTH_BYPASS_DEV", raising=False)
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    monkeypatch.delenv("SESSION_SECRET_KEY", raising=False)


class TestBlockedReason:
    def test_local_sqlite_and_localhost_postgres_are_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert dev_auth_blocked_reason() is None
        for url in (
            "postgresql://u:p@localhost:5432/openbeavs",
            "postgresql+psycopg2://u:p@127.0.0.1:5432/openbeavs",
            "postgresql://u:p@[::1]/openbeavs",
        ):
            monkeypatch.setenv("DATABASE_URL", url)
            assert dev_auth_blocked_reason() is None

    @pytest.mark.parametrize("marker", CLOUD_RUN_MARKERS)
    def test_cloud_run_marker_blocks(
        self, monkeypatch: pytest.MonkeyPatch, marker: str
    ) -> None:
        monkeypatch.setenv(marker, "openbeavs-chat")
        assert marker in (dev_auth_blocked_reason() or "")

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://u:p@10.1.2.3:5432/openbeavs",
            "postgresql://u:p@db.example.test/openbeavs",
            "postgresql://u:p@/openbeavs?host=/cloudsql/proj:region:inst",
            "postgresql://u:p@localhost/test?host=db.example.test",
            "postgresql://u:p@localhost/test?hostaddr=10.1.2.3",
            "postgresql://u:p@localhost/test?service=prod",
            "not a url",
        ],
    )
    def test_non_local_database_blocks(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", url)
        assert dev_auth_blocked_reason() is not None


class TestStartupChecks:
    def test_refuses_startup_when_dev_bypass_enabled_on_cloud_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTH_BYPASS_DEV", "true")
        monkeypatch.setenv("AUTH_SECRET_KEY", VALID_PROD_SECRET)
        monkeypatch.setenv("K_SERVICE", "openbeavs-chat")
        with pytest.raises(RuntimeError, match="AUTH_BYPASS_DEV"):
            check_auth_config()
        with pytest.raises(RuntimeError), TestClient(app):
            pass

    def test_refuses_startup_when_dev_bypass_enabled_with_remote_db(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTH_BYPASS_DEV", "true")
        monkeypatch.setenv("AUTH_SECRET_KEY", VALID_PROD_SECRET)
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@10.0.0.5/openbeavs")
        with pytest.raises(RuntimeError, match="AUTH_BYPASS_DEV"):
            check_auth_config()

    @pytest.mark.parametrize(
        "bad_secret",
        [
            "",
            "too-short",
            "change-this-in-production-to-a-secure-32-byte-secret",
            "openbeavs-dev-fallback-secret-key-change-in-production",
        ],
    )
    def test_refuses_missing_or_placeholder_secret_in_deployment(
        self, monkeypatch: pytest.MonkeyPatch, bad_secret: str
    ) -> None:
        monkeypatch.setenv("K_SERVICE", "openbeavs-chat")
        monkeypatch.setenv("AUTH_SECRET_KEY", bad_secret)
        with pytest.raises(ConfigError):
            AuthConfig.session_secret_key()
        with pytest.raises(RuntimeError), TestClient(app):
            pass

    def test_allows_deployment_with_bypass_off_and_strong_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("K_SERVICE", "openbeavs-chat")
        monkeypatch.setenv("AUTH_BYPASS_DEV", "false")
        monkeypatch.setenv("AUTH_SECRET_KEY", VALID_PROD_SECRET)
        check_auth_config()
        assert AuthConfig.session_secret_key() == VALID_PROD_SECRET


class TestRuntimeFailClosed:
    def test_dev_login_and_header_bypass_fail_closed_on_cloud_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTH_BYPASS_DEV", "true")
        monkeypatch.setenv("AUTH_SECRET_KEY", VALID_PROD_SECRET)
        monkeypatch.setenv("K_SERVICE", "openbeavs-chat")

        client = TestClient(app)
        assert (
            client.post(
                "/auth/dev/login", json={"email": "alice@oregonstate.edu"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/auth/me", headers={"X-Dev-User-Email": "alice@oregonstate.edu"}
            ).status_code
            == 401
        )
