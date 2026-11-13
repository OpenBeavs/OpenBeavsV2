"""Who may call the registry's A2A endpoint.

Google token checking is faked (no GCP credentials, no network), so these run on
any machine. The real ``id_token.verify_oauth2_token`` is only checked for how it
is called.
"""

import time

import httpx
import pytest
from sqlalchemy.orm import Session

from app.registry.a2a import MOUNT_PATH
from app.registry.a2a_auth import (
    AuthError,
    GoogleTokenVerifier,
    build_verifier,
    open_verifier,
)

from .a2a_helpers import BASE, Harness, llm_choosing, rpc, run, v1_message

CHRIS = "chris-runtime@project.iam.gserviceaccount.com"
RPC_PATH = f"{MOUNT_PATH}/"
CARD_PATH = f"{MOUNT_PATH}/.well-known/agent-card.json"
V1 = {"A2A-Version": "1.0"}


def claims(email: str = CHRIS, verified: bool = True, exp_in: int = 3600) -> dict:
    return {"email": email, "email_verified": verified, "exp": time.time() + exp_in}


class FakeGoogle:
    """Stands in for Google's token verification and records how it was used."""

    def __init__(self, result: dict | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def __call__(self, token: str, audience: str) -> dict:
        self.calls.append((token, audience))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def verifier(
    google: FakeGoogle, allowed: set[str] | None = None
) -> GoogleTokenVerifier:
    return GoogleTokenVerifier(
        audience=BASE, allowed_callers=allowed or {CHRIS}, verify_token=google
    )


class TestGoogleTokenVerifier:
    def test_an_allowed_service_account_is_accepted(self) -> None:
        google = FakeGoogle(claims())
        caller = run(verifier(google)("good-token"))
        assert caller.identity == CHRIS
        assert google.calls == [("good-token", BASE)]

    def test_email_matching_ignores_case(self) -> None:
        caller = run(verifier(FakeGoogle(claims(email=CHRIS.upper())))("t"))
        assert caller.identity == CHRIS

    @pytest.mark.parametrize("token", [None, ""])
    def test_a_missing_token_is_401(self, token) -> None:
        with pytest.raises(AuthError) as error:
            run(verifier(FakeGoogle(claims()))(token))
        assert error.value.status_code == 401

    @pytest.mark.parametrize(
        "problem",
        [ValueError("Token expired"), ValueError("Wrong audience"), Exception("x")],
    )
    def test_an_invalid_or_expired_token_is_401(self, problem: Exception) -> None:
        with pytest.raises(AuthError) as error:
            run(verifier(FakeGoogle(problem))("bad"))
        assert error.value.status_code == 401

    def test_a_valid_token_for_someone_else_is_403(self) -> None:
        google = FakeGoogle(
            claims(email="someone-else@project.iam.gserviceaccount.com")
        )
        with pytest.raises(AuthError) as error:
            run(verifier(google)("t"))
        assert error.value.status_code == 403

    @pytest.mark.parametrize("bad", [claims(verified=False), {"email_verified": True}])
    def test_an_unverified_or_missing_email_is_401(self, bad: dict) -> None:
        with pytest.raises(AuthError) as error:
            run(verifier(FakeGoogle(bad))("t"))
        assert error.value.status_code == 401

    def test_a_verified_token_is_not_rechecked_with_google_every_time(self) -> None:
        google = FakeGoogle(claims())
        check = verifier(google)
        run(check("same"))
        run(check("same"))
        assert len(google.calls) == 1

    def test_an_expired_cache_entry_is_rechecked(self) -> None:
        google = FakeGoogle(claims(exp_in=-10))  # already expired when cached
        check = verifier(google)
        run(check("t"))
        run(check("t"))
        assert len(google.calls) == 2

    def test_a_rejected_token_is_never_cached(self) -> None:
        google = FakeGoogle(ValueError("bad"))
        check = verifier(google)
        for _ in range(2):
            with pytest.raises(AuthError):
                run(check("t"))
        assert len(google.calls) == 2

    def test_google_is_asked_to_check_the_audience(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from google.oauth2 import id_token

        seen: dict = {}

        def fake_verify(token, request, audience=None, **kwargs):
            seen.update(token=token, audience=audience)
            return claims()

        monkeypatch.setattr(id_token, "verify_oauth2_token", fake_verify)
        real = GoogleTokenVerifier(
            audience="https://registry.example", allowed_callers={CHRIS}
        )
        assert run(real("tok")).identity == CHRIS
        assert seen == {"token": "tok", "audience": "https://registry.example"}


class TestBuildVerifier:
    @pytest.fixture(autouse=True)
    def clean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in (
            "K_SERVICE",
            "K_REVISION",
            "K_CONFIGURATION",
            "REGISTRY_A2A_AUTH",
            "REGISTRY_A2A_ALLOWED_CALLERS",
            "REGISTRY_A2A_AUDIENCE",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./local.db")

    def refused(self, check) -> int:
        with pytest.raises(AuthError) as error:
            run(check("any-token"))
        return error.value.status_code

    def test_locally_with_nothing_set_it_is_open(self) -> None:
        assert build_verifier(BASE) is open_verifier

    def test_on_cloud_run_with_nothing_set_it_is_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("K_SERVICE", "openbeavs-registry-agent")
        assert self.refused(build_verifier(BASE)) == 503

    def test_open_mode_is_refused_on_cloud_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("K_SERVICE", "openbeavs-registry-agent")
        monkeypatch.setenv("REGISTRY_A2A_AUTH", "dev")
        assert self.refused(build_verifier(BASE)) == 503

    def test_open_mode_is_refused_with_a_shared_database(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_A2A_AUTH", "dev")
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql://u:p@localhost/openbeavs_v2?host=db.example.test",
        )
        assert self.refused(build_verifier(BASE)) == 503

    def test_google_mode_needs_an_allow_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_A2A_AUTH", "google")
        assert self.refused(build_verifier(BASE)) == 503

    def test_google_mode_with_an_allow_list_checks_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_A2A_AUTH", "google")
        monkeypatch.setenv("REGISTRY_A2A_ALLOWED_CALLERS", f" {CHRIS} , other@x.test ")
        check = build_verifier(BASE)
        assert isinstance(check, GoogleTokenVerifier)
        assert self.refused(check) == 401  # not a real token

    def test_the_audience_defaults_to_the_public_url_and_can_be_overridden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_A2A_AUTH", "google")
        monkeypatch.setenv("REGISTRY_A2A_ALLOWED_CALLERS", CHRIS)
        assert (
            build_verifier("https://registry.example")._audience
            == "https://registry.example"
        )
        monkeypatch.setenv("REGISTRY_A2A_AUDIENCE", "https://other.example")
        assert (
            build_verifier("https://registry.example")._audience
            == "https://other.example"
        )

    def test_an_unknown_mode_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_A2A_AUTH", "none-of-the-above")
        assert self.refused(build_verifier(BASE)) == 503


class TestOverHttp:
    def harness(self, db: Session, google: FakeGoogle) -> Harness:
        return Harness(db, llm_choosing("none"), verifier=verifier(google))

    def call(self, db: Session, google: FakeGoogle, headers: dict) -> httpx.Response:
        async def scenario() -> httpx.Response:
            async with self.harness(db, google).http() as http:
                return await http.post(
                    RPC_PATH, json=rpc("SendMessage", v1_message()), headers=headers
                )

        return run(scenario())

    def test_no_token_is_401_with_a_challenge(self, db: Session) -> None:
        response = self.call(db, FakeGoogle(claims()), V1)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert "result" not in response.text

    def test_a_good_token_reaches_the_agent(self, db: Session) -> None:
        response = self.call(
            db, FakeGoogle(claims()), {**V1, "Authorization": "Bearer good"}
        )
        assert response.status_code == 200
        assert "result" in response.json()

    def test_the_wrong_caller_is_403(self, db: Session) -> None:
        google = FakeGoogle(claims(email="intruder@x.test"))
        response = self.call(db, google, {**V1, "Authorization": "Bearer good"})
        assert response.status_code == 403

    def test_a_bad_token_is_401(self, db: Session) -> None:
        response = self.call(
            db, FakeGoogle(ValueError("expired")), {**V1, "Authorization": "Bearer old"}
        )
        assert response.status_code == 401

    @pytest.mark.parametrize("header", ["Basic abc", "Bearer", "bearer ", "Token abc"])
    def test_other_authorization_forms_are_401(self, db: Session, header: str) -> None:
        response = self.call(db, FakeGoogle(claims()), {**V1, "Authorization": header})
        assert response.status_code == 401

    def test_the_agent_card_stays_public_so_clients_can_discover_it(
        self, db: Session
    ) -> None:
        async def scenario() -> httpx.Response:
            async with self.harness(db, FakeGoogle(claims())).http() as http:
                return await http.get(CARD_PATH)

        assert run(scenario()).status_code == 200

    def test_only_get_on_the_card_is_public(self, db: Session) -> None:
        async def scenario() -> httpx.Response:
            async with self.harness(db, FakeGoogle(claims())).http() as http:
                return await http.post(CARD_PATH, json={})

        assert run(scenario()).status_code == 401

    def test_a_misconfigured_verifier_fails_closed_with_503(self, db: Session) -> None:
        from app.registry.a2a_auth import deny_all

        async def scenario() -> httpx.Response:
            harness = Harness(db, verifier=deny_all("no allow list"))
            async with harness.http() as http:
                return await http.post(RPC_PATH, json=rpc("SendMessage", v1_message()))

        assert run(scenario()).status_code == 503
