"""Auto approval (the default) and manual approval of new submissions.

In auto mode an agent that passes every automated check goes live as
``provisional`` with no human review. Flagged cards still wait for a person, and
manual mode keeps every submission pending.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Agent
from app.registry.service import (
    APPROVAL_AUTO,
    APPROVAL_MANUAL,
    approval_mode,
    routable_agents,
    submit_agent,
)
from tests.registry.conftest import (
    ADMIN_EMAIL,
    FakeFetcher,
    as_user,
    make_card,
)

STEERING = "Card text looks like an attempt to steer Chris's routing."


@pytest.fixture
def default_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave REGISTRY_APPROVAL_MODE unset, as in a fresh deployment."""
    monkeypatch.delenv("REGISTRY_APPROVAL_MODE", raising=False)


class TestMode:
    def test_default_is_auto(self, default_mode: None) -> None:
        assert approval_mode() == APPROVAL_AUTO

    @pytest.mark.parametrize("value", ["auto", "AUTO", " auto "])
    def test_auto_is_recognised(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("REGISTRY_APPROVAL_MODE", value)
        assert approval_mode() == APPROVAL_AUTO

    def test_manual_is_recognised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REGISTRY_APPROVAL_MODE", "manual")
        assert approval_mode() == APPROVAL_MANUAL

    @pytest.mark.parametrize("value", ["yes", "approve", "true", "none"])
    def test_unknown_value_falls_back_to_manual(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("REGISTRY_APPROVAL_MODE", value)
        assert approval_mode() == APPROVAL_MANUAL

    def test_blank_value_uses_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A copied .env.example leaves the variable blank, which means "not set".
        monkeypatch.setenv("REGISTRY_APPROVAL_MODE", "")
        assert approval_mode() == APPROVAL_AUTO


class TestAutoApproval:
    def test_a_clean_card_goes_live_as_provisional(
        self, db: Session, default_mode: None
    ) -> None:
        agent = submit_agent(db, make_card(), submitted_by="alice@example.test")
        assert (agent.status, agent.is_active) == ("provisional", True)
        assert agent.trust_tier == "public"
        assert agent.required_role is None
        assert agent.is_featured is False
        assert agent.reviewed_by == "system:auto"
        assert agent.reviewed_at is not None
        assert "Auto-approved" in agent.review_note
        assert agent in routable_agents(db)

    def test_a_flagged_card_waits_for_a_person(
        self, db: Session, default_mode: None
    ) -> None:
        agent = submit_agent(
            db, make_card(flags=[STEERING]), submitted_by="alice@example.test"
        )
        assert (agent.status, agent.is_active) == ("pending", False)
        assert agent.reviewed_by is None
        assert agent.reviewed_at is None
        assert agent.review_note == STEERING
        assert agent not in routable_agents(db)

    def test_manual_mode_keeps_every_card_pending(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_APPROVAL_MODE", "manual")
        agent = submit_agent(db, make_card(), submitted_by="alice@example.test")
        assert (agent.status, agent.is_active) == ("pending", False)
        assert agent.reviewed_by is None
        assert agent not in routable_agents(db)

    def test_the_submitter_still_cannot_choose_the_outcome(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("REGISTRY_APPROVAL_MODE")
        response = client.post(
            "/registry/agents",
            json={"url": "https://math.example.test", "status": "approved"},
            headers=as_user(),
        )
        assert response.status_code == 422


class TestOverTheApi:
    def test_submission_is_routable_immediately_in_auto_mode(
        self, client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("REGISTRY_APPROVAL_MODE")
        response = client.post(
            "/registry/agents",
            json={"url": "https://math.example.test"},
            headers=as_user(),
        )
        assert response.status_code == 201
        body = response.json()
        assert (body["status"], body["is_active"]) == ("provisional", True)
        assert body["reviewed_by"] == "system:auto"

        listed = {agent["name"] for agent in client.get("/chat/agents").json()}
        assert "Math Test Agent" in listed

    def test_an_auto_approved_agent_can_still_be_revoked(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("REGISTRY_APPROVAL_MODE")
        created = client.post(
            "/registry/agents",
            json={"url": "https://math.example.test"},
            headers=as_user(),
        ).json()

        revoked = client.post(
            f"/registry/agents/{created['id']}/review",
            json={"action": "revoke", "note": "no longer wanted"},
            headers=as_user(ADMIN_EMAIL),
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        listed = {agent["name"] for agent in client.get("/chat/agents").json()}
        assert "Math Test Agent" not in listed

    def test_a_flagged_card_over_the_api_stays_pending(
        self, client: TestClient, fetcher: FakeFetcher, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("REGISTRY_APPROVAL_MODE")
        fetcher.add(
            "https://sneaky.example.test",
            make_card("Sneaky", "https://sneaky.example.test", flags=[STEERING]),
        )
        response = client.post(
            "/registry/agents",
            json={"url": "https://sneaky.example.test"},
            headers=as_user(),
        )
        assert response.status_code == 201
        assert response.json()["status"] == "pending"
        listed = {agent["name"] for agent in client.get("/chat/agents").json()}
        assert "Sneaky" not in listed

    def test_duplicates_are_still_refused_in_auto_mode(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("REGISTRY_APPROVAL_MODE")
        url = {"url": "https://math.example.test"}
        assert (
            client.post("/registry/agents", json=url, headers=as_user()).status_code
            == 201
        )
        assert (
            client.post("/registry/agents", json=url, headers=as_user()).status_code
            == 409
        )

    def test_an_auto_approved_row_is_a_normal_agent_row(
        self, client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("REGISTRY_APPROVAL_MODE")
        created = client.post(
            "/registry/agents",
            json={"url": "https://math.example.test"},
            headers=as_user(),
        ).json()
        row = db.get(Agent, created["id"])
        assert row.submitted_by == "alice@example.test"
        assert row.endpoint_url == "https://math.example.test/"
