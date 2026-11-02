"""REGISTRY_DEV_AUTH must never work in a deployment-like environment."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.registry.auth import check_dev_auth_config, dev_auth_blocked_reason
from tests.registry.conftest import ADMIN_EMAIL, as_user

CLOUD_RUN_MARKERS = ["K_SERVICE", "K_REVISION", "K_CONFIGURATION"]


@pytest.fixture(autouse=True)
def local_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from a clean local environment."""
    for marker in CLOUD_RUN_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./local.db")
    # A developer's backend/.env may enable it; tests must not depend on that.
    monkeypatch.delenv("REGISTRY_DEV_AUTH", raising=False)


class TestBlockedReason:
    def test_local_sqlite_is_allowed(self) -> None:
        assert dev_auth_blocked_reason() is None

    def test_unset_database_url_defaults_to_local_sqlite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL")
        assert dev_auth_blocked_reason() is None

    @pytest.mark.parametrize("marker", CLOUD_RUN_MARKERS)
    def test_cloud_run_marker_blocks(
        self, monkeypatch: pytest.MonkeyPatch, marker: str
    ) -> None:
        monkeypatch.setenv(marker, "openbeavs")
        assert marker in (dev_auth_blocked_reason() or "")

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://u:p@10.1.2.3:5432/openbeavs_v2",
            "postgresql://u:p@db.example.test/openbeavs_v2",
            "postgresql://u:p@/openbeavs_v2?host=/cloudsql/proj:region:inst",
            "postgresql://u:p@/openbeavs_v2",
            # libpq lets query parameters override the host in the URL
            "postgresql://u:p@localhost/test?host=db.example.test",
            "postgresql://u:p@localhost/test?HOST=db.example.test",
            "postgresql://u:p@localhost/test?hostaddr=10.1.2.3",
            "postgresql://u:p@db.example.test/test?hostaddr=127.0.0.1",
            "postgresql://u:p@localhost/test?service=prod",
            "postgresql://u:p@localhost/test?host=localhost,db.example.test",
            "postgresql://u:p@localhost,db.example.test/test",
            "postgresql://u:p@/test?host=/cloudsql/proj:region:inst",
            "postgresql+psycopg2://u:p@localhost/test?host=db.example.test",
            "postgresql://u:p@localhost.example.test/test",
            "postgresql://u:p@127.0.0.1.nip.io/test",
        ],
    )
    def test_non_local_database_blocks(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", url)
        assert dev_auth_blocked_reason() is not None

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://u:p@localhost:5432/dev",
            "postgresql://u:p@LOCALHOST/dev",
            "postgresql://u:p@127.0.0.1/dev",
            "postgresql://u:p@[::1]/dev",
            "postgresql://u:p@/dev?host=localhost",
            "postgresql://u:p@localhost/dev?host=127.0.0.1&hostaddr=127.0.0.1",
            "postgresql+psycopg2://u:p@localhost/dev?sslmode=disable",
            "sqlite:///./dev.db",
            "sqlite:///:memory:",
        ],
    )
    def test_local_databases_are_allowed(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", url)
        assert dev_auth_blocked_reason() is None

    def test_unparseable_database_url_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "not a url")
        assert dev_auth_blocked_reason() is not None


class TestStartupCheck:
    def test_fails_when_enabled_on_cloud_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_DEV_AUTH", "true")
        monkeypatch.setenv("K_SERVICE", "openbeavs")
        with pytest.raises(RuntimeError, match="REGISTRY_DEV_AUTH"):
            check_dev_auth_config()

    def test_app_refuses_to_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REGISTRY_DEV_AUTH", "true")
        monkeypatch.setenv("K_SERVICE", "openbeavs")
        with pytest.raises(RuntimeError), TestClient(app):
            pass

    def test_passes_when_disabled_even_on_cloud_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("K_SERVICE", "openbeavs")
        check_dev_auth_config()

    def test_passes_locally(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REGISTRY_DEV_AUTH", "true")
        check_dev_auth_config()


class TestRequests:
    def test_forged_admin_header_is_refused_on_cloud_run(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("K_SERVICE", "openbeavs")
        response = client.post(
            "/registry/agents/anything/review",
            json={"action": "approve"},
            headers=as_user(ADMIN_EMAIL),
        )
        assert response.status_code == 501

    def test_forged_header_is_refused_with_a_shared_database(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@10.1.2.3/openbeavs_v2")
        response = client.get("/registry/agents", headers=as_user(ADMIN_EMAIL))
        assert response.status_code == 501

    def test_host_override_bypass_is_refused(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql://u:placeholder@localhost/test?host=db.example.test",
        )
        response = client.get("/registry/agents", headers=as_user(ADMIN_EMAIL))
        assert response.status_code == 501

    def test_dev_auth_still_works_locally(self, client: TestClient) -> None:
        response = client.get("/registry/agents", headers=as_user(ADMIN_EMAIL))
        assert response.status_code == 200
