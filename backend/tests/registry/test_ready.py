"""/health is liveness; /ready checks the database and required configuration.

Readiness must never make a paid model request and must never echo settings or
connection details.
"""

import os
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.registry import a2a_app, llm
from app.registry.a2a_app import create_standalone_app

SECRET_KEY = "SECRET-KEY-VALUE-5521"
SECRET_ALLOWED = "caller-secret@example.test"
PUBLIC_URL = "https://registry.example.run.app"
CARD_PATH = "/a2a/registry/.well-known/agent-card.json"

CONFIG = {
    "REGISTRY_PUBLIC_URL": PUBLIC_URL,
    "REGISTRY_A2A_AUTH": "google",
    "REGISTRY_A2A_ALLOWED_CALLERS": SECRET_ALLOWED,
    "REGISTRY_MODEL": "test-model",
    "REGISTRY_GEMINI_API_KEY": SECRET_KEY,
}
ALL_VARIABLES = (
    *CONFIG,
    "GEMINI_API_KEY",
    "REGISTRY_A2A_AUDIENCE",
    "K_SERVICE",
    "K_REVISION",
    "K_CONFIGURATION",
)


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fully configured service; each test removes one thing."""
    for name in ALL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    for name, value in CONFIG.items():
        monkeypatch.setenv(name, value)


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Readiness is free: any attempt to reach Gemini fails the test."""
    attempts: list[str] = []

    async def forbidden(*args, **kwargs) -> str:
        attempts.append("generate_json")
        raise AssertionError("readiness must not call the model")

    def forbidden_request(self, request):
        attempts.append(str(request.url))
        raise AssertionError("readiness must not use the network")

    monkeypatch.setattr(llm, "generate_json", forbidden)
    # The real network transports only; the test client uses its own in-memory one.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden_request)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", forbidden_request
    )
    return attempts


@pytest.fixture
def factory(db: Session) -> Callable[[], Session]:
    """Sessions on the migrated test database."""
    return sessionmaker(bind=db.get_bind(), expire_on_commit=False)


def client_for(factory: Callable[[], Session]) -> TestClient:
    return TestClient(create_standalone_app(session_factory=factory))


class TestReady:
    def test_everything_in_place_is_ready(self, factory) -> None:
        response = client_for(factory).get("/ready")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "checks": {
                "database": "ok",
                "public_url": "ok",
                "auth": "ok",
                "model": "ok",
                "model_key": "ok",
            },
        }

    def test_the_generic_gemini_key_is_enough(
        self, factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("REGISTRY_GEMINI_API_KEY")
        monkeypatch.setenv("GEMINI_API_KEY", SECRET_KEY)
        assert client_for(factory).get("/ready").status_code == 200

    @pytest.mark.parametrize(
        ("missing", "check"),
        [
            ("REGISTRY_MODEL", "model"),
            ("REGISTRY_GEMINI_API_KEY", "model_key"),
            ("REGISTRY_A2A_ALLOWED_CALLERS", "auth"),
        ],
    )
    def test_missing_configuration_is_not_ready(
        self, factory, monkeypatch: pytest.MonkeyPatch, missing: str, check: str
    ) -> None:
        monkeypatch.delenv(missing)
        response = client_for(factory).get("/ready")
        body = response.json()
        assert response.status_code == 503 and body["status"] == "not_ready"
        assert body["checks"][check] == "failed"
        assert [k for k, v in body["checks"].items() if v == "failed"] == [check]

    @pytest.mark.parametrize(
        ("settings", "unset", "check"),
        [
            ({"REGISTRY_MODEL": "   "}, (), "model"),
            ({"K_SERVICE": "registry"}, ("REGISTRY_PUBLIC_URL",), "public_url"),
            ({"K_SERVICE": "registry", "REGISTRY_A2A_AUTH": "dev"}, (), "auth"),
            ({"REGISTRY_A2A_AUTH": "nonsense"}, (), "auth"),
        ],
        ids=["blank-model", "missing-cloud-origin", "cloud-dev-auth", "unknown-auth"],
    )
    def test_unusable_configuration_is_not_ready(
        self, factory, monkeypatch, settings, unset, check
    ):
        for name in unset:
            monkeypatch.delenv(name)
        for name, value in settings.items():
            monkeypatch.setenv(name, value)
        response = client_for(factory).get("/ready")
        assert response.status_code == 503
        assert response.json()["checks"][check] == "failed"

    def test_an_unreachable_database_is_not_ready(self) -> None:
        def down() -> Session:
            raise OperationalError("select", {}, Exception("password=hunter2 host=db"))

        response = client_for(down).get("/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["database"] == "failed"
        assert "hunter2" not in response.text

    def test_a_database_that_was_never_migrated_is_not_ready(self) -> None:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )  # no tables at all
        response = client_for(sessionmaker(bind=engine)).get("/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["database"] == "failed"

    def test_a_database_missing_the_review_columns_is_not_ready(self) -> None:
        """The agents table exists but predates the registry migration."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE agents (id VARCHAR(64) PRIMARY KEY, name VARCHAR(128), "
                "endpoint_url VARCHAR(512), trust_tier VARCHAR(32), "
                "required_role VARCHAR(64), is_active BOOLEAN)"
            )
        response = client_for(sessionmaker(bind=engine)).get("/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["database"] == "failed"

    def test_it_recovers_when_the_database_comes_back(self, db: Session) -> None:
        real = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
        state = {"up": False}

        def maybe() -> Session:
            if not state["up"]:
                raise OperationalError("select", {}, Exception("down"))
            return real()

        client = client_for(maybe)
        assert client.get("/ready").status_code == 503
        state["up"] = True
        assert client.get("/ready").status_code == 200


class TestReadyIsSafe:
    def test_it_never_calls_the_model_or_the_network(
        self, factory, no_model_calls: list[str]
    ) -> None:
        client = client_for(factory)
        for _ in range(3):
            assert client.get("/ready").status_code == 200
        assert no_model_calls == []

    def test_it_returns_no_setting_values(self, factory) -> None:
        text = client_for(factory).get("/ready").text
        for value in (SECRET_KEY, SECRET_ALLOWED, PUBLIC_URL, "test-model"):
            assert value not in text

    def test_logs_name_variables_not_values(
        self, factory, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        monkeypatch.delenv("REGISTRY_MODEL")
        client_for(factory).get("/ready")
        assert "REGISTRY_MODEL" in caplog.text
        for value in (SECRET_KEY, SECRET_ALLOWED):
            assert value not in caplog.text

    def test_it_needs_no_token(self, factory) -> None:
        """Probes cannot send one; the A2A endpoint itself still requires it."""
        client = client_for(factory)
        assert client.get("/ready").status_code == 200
        assert client.post("/a2a/registry/", json={}).status_code == 401


class TestHealthStaysLiveness:
    def test_health_is_ok_even_when_not_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def down() -> Session:
            raise OperationalError("select", {}, Exception("down"))

        monkeypatch.delenv("REGISTRY_MODEL")
        client = client_for(down)
        assert client.get("/ready").status_code == 503
        response = client.get("/health")
        assert response.status_code == 200 and response.json()["status"] == "ok"

    def test_health_does_not_touch_the_database(self) -> None:
        touched: list[int] = []

        def tracking() -> Session:
            touched.append(1)
            raise AssertionError("health must not open a session")

        assert client_for(tracking).get("/health").status_code == 200
        assert touched == []


MALFORMED_ORIGINS = [
    "not a url",
    "registry.example.run.app",  # no scheme
    "https://",
    "https:///path",
    "ftp://registry.example.run.app",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "https://user:password@registry.example.run.app",
    "https://registry.example.run.app/a2a/registry",  # a path is not an origin
    "https://registry.example.run.app?x=1",
    "https://registry.example.run.app/?x=1",
    "https://registry.example.run.app#frag",
    "https://registry.example.run.app:notaport",
    "https://registry.example.run.app:99999",
    "https://registry .example.run.app",
    r"https://registry.example.run.app\evil",
    "https://regis\x00try.example.run.app",
]


class TestMalformedPublicUrl:
    """A bad REGISTRY_PUBLIC_URL used to pass readiness and ship a broken card."""

    @pytest.fixture(autouse=True)
    def posix_environment_rules(self, monkeypatch):
        """Catch invalid environment injection on Windows as well as Linux CI."""
        putenv = os.putenv

        def reject_null(key, value):
            if (b"\x00" if isinstance(value, bytes) else "\x00") in value:
                raise ValueError("embedded null byte")
            return putenv(key, value)

        monkeypatch.setattr(os, "putenv", reject_null)

    @pytest.mark.parametrize("probe", ["ready", "a2a"])
    @pytest.mark.parametrize("bad", MALFORMED_ORIGINS)
    def test_malformed_origin_fails_closed(self, factory, monkeypatch, bad, probe):
        # Linux rejects NUL in os.environ before our URL validator can inspect it.
        # Inject at the configuration boundary to exercise the same failure path
        # on every platform, including values the OS cannot represent.
        get_env = a2a_app.get_env
        monkeypatch.setattr(
            a2a_app,
            "get_env",
            lambda name, default="": bad
            if name == "REGISTRY_PUBLIC_URL"
            else get_env(name, default),
        )
        client = client_for(factory)
        if probe == "ready":
            response = client.get("/ready")
            assert response.status_code == 503
            assert response.json()["checks"]["public_url"] == "failed"
        else:
            assert client.get(CARD_PATH).status_code == 503
            assert client.post("/a2a/registry/", json={}).status_code == 503

    @pytest.mark.parametrize(
        "bad", ["http://registry.example.run.app", "HTTP://x.test"]
    )
    def test_http_is_refused_on_cloud_run(
        self, factory, monkeypatch: pytest.MonkeyPatch, bad: str
    ) -> None:
        monkeypatch.setenv("K_SERVICE", "registry")
        monkeypatch.setenv("REGISTRY_PUBLIC_URL", bad)
        assert client_for(factory).get("/ready").json()["checks"]["public_url"] == (
            "failed"
        )

    @pytest.mark.parametrize(
        ("given", "advertised"),
        [
            (PUBLIC_URL, PUBLIC_URL),
            (PUBLIC_URL + "/", PUBLIC_URL),
            (
                "https://registry.example.run.app:8443",
                "https://registry.example.run.app:8443",
            ),
            ("HTTPS://Registry.Example.Run.App", "https://Registry.Example.Run.App"),
        ],
    )
    def test_valid_origins_are_accepted_and_advertised_cleanly(
        self, factory, monkeypatch: pytest.MonkeyPatch, given: str, advertised: str
    ) -> None:
        monkeypatch.setenv("K_SERVICE", "registry")
        monkeypatch.setenv("REGISTRY_PUBLIC_URL", given)
        client = client_for(factory)
        assert client.get("/ready").status_code == 200
        card = client.get(CARD_PATH).json()
        assert card["supportedInterfaces"][0]["url"] == f"{advertised}/a2a/registry/"

    def test_http_is_still_fine_for_local_development(
        self, factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_PUBLIC_URL", "http://127.0.0.1:8000")
        assert client_for(factory).get("/ready").status_code == 200

    def test_the_value_is_never_echoed(
        self, factory, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        monkeypatch.setenv("REGISTRY_PUBLIC_URL", "https://user:hunter2@bad.example")
        client = client_for(factory)
        text = client.get("/ready").text + client.get(CARD_PATH).text + caplog.text
        assert "hunter2" not in text

    def test_the_default_token_audience_is_the_validated_origin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.registry.a2a_app import public_base_url
        from app.registry.a2a_auth import GoogleTokenVerifier, build_verifier

        monkeypatch.setenv("REGISTRY_PUBLIC_URL", PUBLIC_URL + "/")
        verifier = build_verifier(public_base_url())
        assert isinstance(verifier, GoogleTokenVerifier)
        assert verifier._audience == PUBLIC_URL
