"""The registry API: submission, visibility, and the admin review gate."""

import pytest
from fastapi.testclient import TestClient

from app.registry.cards import CardError
from app.registry.security import UnsafeURLError

from .conftest import (
    ADMIN_EMAIL,
    OTHER_EMAIL,
    USER_EMAIL,
    FakeFetcher,
    as_user,
    make_card,
)


def review(client: TestClient, agent_id: str, action: str, **extra):
    """Post an admin review decision and return the response."""
    return client.post(
        f"/registry/agents/{agent_id}/review",
        json={"action": action, **extra},
        headers=as_user(ADMIN_EMAIL),
    )


class TestSubmission:
    def test_submission_creates_a_pending_unroutable_entry(self, submit) -> None:
        agent = submit()
        assert agent["status"] == "pending"
        assert agent["is_active"] is False
        assert agent["trust_tier"] == "public"
        assert agent["is_featured"] is False
        assert agent["name"] == "Math Test Agent"
        assert agent["card_url"] == "https://math.example.test/.well-known/agent.json"
        assert agent["endpoint_url"] == "https://math.example.test/"
        assert agent["skills"][0]["id"] == "arithmetic"
        assert agent["submitted_by"] == USER_EMAIL

    def test_id_is_generated_by_the_server(self, submit) -> None:
        assert len(submit()["id"]) == 36

    @pytest.mark.parametrize(
        "body",
        [
            {"url": "https://math.example.test", "status": "approved"},
            {"url": "https://math.example.test", "trust_tier": "privileged"},
            {"url": "https://math.example.test", "is_active": True},
            {"url": "https://math.example.test", "id": "chris"},
        ],
    )
    def test_clients_cannot_set_status_tier_or_anything_else(
        self, client: TestClient, body: dict
    ) -> None:
        response = client.post("/registry/agents", json=body, headers=as_user())
        assert response.status_code == 422

    def test_empty_url_is_rejected(self, client: TestClient) -> None:
        response = client.post("/registry/agents", json={"url": ""}, headers=as_user())
        assert response.status_code == 422

    def test_duplicate_card_url_is_a_conflict(self, client: TestClient, submit) -> None:
        submit()
        response = client.post(
            "/registry/agents",
            json={"url": "https://math.example.test"},
            headers=as_user(OTHER_EMAIL),
        )
        assert response.status_code == 409

    def test_unreachable_card_is_a_bad_request(
        self, client: TestClient, fetcher: FakeFetcher
    ) -> None:
        fetcher.add(
            "https://down.example.test", CardError("Could not reach the agent card.")
        )
        response = client.post(
            "/registry/agents",
            json={"url": "https://down.example.test"},
            headers=as_user(),
        )
        assert response.status_code == 400
        assert "Could not reach" in response.json()["detail"]

    def test_unsafe_address_is_a_bad_request(
        self, client: TestClient, fetcher: FakeFetcher
    ) -> None:
        fetcher.add(
            "https://10.0.0.1",
            UnsafeURLError("Host 10.0.0.1 resolves to a non-public address."),
        )
        response = client.post(
            "/registry/agents", json={"url": "https://10.0.0.1"}, headers=as_user()
        )
        assert response.status_code == 400
        assert "non-public" in response.json()["detail"]

    def test_steering_text_is_flagged_for_the_reviewer(
        self, client: TestClient, fetcher: FakeFetcher
    ) -> None:
        flagged = make_card(
            name="Helpful Weather Pro",
            url="https://weather.example.test",
            flags=["Card text looks like an attempt to steer Chris's routing."],
        )
        fetcher.add("https://weather.example.test", flagged)
        response = client.post(
            "/registry/agents",
            json={"url": "https://weather.example.test"},
            headers=as_user(),
        )
        assert response.status_code == 201
        assert "steer" in response.json()["review_note"]
        assert response.json()["status"] == "pending"


class TestAuthentication:
    def test_without_configured_auth_every_route_fails_closed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("REGISTRY_DEV_AUTH")
        assert client.get("/registry/agents").status_code == 501
        assert (
            client.post("/registry/agents", json={"url": "https://x.test"}).status_code
            == 501
        )

    def test_missing_dev_headers_are_unauthorized(self, client: TestClient) -> None:
        assert client.get("/registry/agents").status_code == 401

    def test_admin_is_recognised_by_email_case_insensitively(
        self, client: TestClient, submit
    ) -> None:
        agent = submit()
        response = client.post(
            f"/registry/agents/{agent['id']}/review",
            json={"action": "approve"},
            headers=as_user(ADMIN_EMAIL.upper()),
        )
        assert response.status_code == 200


class TestVisibility:
    def test_pending_entry_is_visible_only_to_its_submitter_and_admins(
        self, client: TestClient, submit
    ) -> None:
        agent = submit()
        path = f"/registry/agents/{agent['id']}"

        assert client.get(path, headers=as_user(USER_EMAIL)).status_code == 200
        assert client.get(path, headers=as_user(ADMIN_EMAIL)).status_code == 200
        assert client.get(path, headers=as_user(OTHER_EMAIL)).status_code == 404

        assert (
            len(client.get("/registry/agents", headers=as_user(USER_EMAIL)).json()) == 1
        )
        assert (
            len(client.get("/registry/agents", headers=as_user(ADMIN_EMAIL)).json())
            == 1
        )
        assert client.get("/registry/agents", headers=as_user(OTHER_EMAIL)).json() == []

    def test_approved_entry_is_visible_to_everyone_without_submitter_details(
        self, client: TestClient, submit
    ) -> None:
        agent = submit()
        assert review(client, agent["id"], "approve").status_code == 200

        listed = client.get("/registry/agents", headers=as_user(OTHER_EMAIL)).json()
        assert [a["id"] for a in listed] == [agent["id"]]
        assert listed[0]["submitted_by"] is None
        assert listed[0]["reviewed_by"] is None
        assert listed[0]["review_note"] is None

    def test_submitter_and_admin_see_review_details(
        self, client: TestClient, submit
    ) -> None:
        agent = submit()
        review(client, agent["id"], "approve", note="Looks good")
        for email in (USER_EMAIL, ADMIN_EMAIL):
            seen = client.get(
                f"/registry/agents/{agent['id']}", headers=as_user(email)
            ).json()
            assert seen["submitted_by"] == USER_EMAIL
            assert seen["reviewed_by"] == ADMIN_EMAIL
            assert seen["review_note"] == "Looks good"

    def test_revoked_entry_disappears_for_others_but_not_the_submitter(
        self, client: TestClient, submit
    ) -> None:
        agent = submit()
        review(client, agent["id"], "approve")
        review(client, agent["id"], "revoke", note="Policy violation")

        path = f"/registry/agents/{agent['id']}"
        assert client.get(path, headers=as_user(OTHER_EMAIL)).status_code == 404
        assert (
            client.get(path, headers=as_user(USER_EMAIL)).json()["status"] == "revoked"
        )

    def test_status_filter(
        self, client: TestClient, submit, fetcher: FakeFetcher
    ) -> None:
        fetcher.add(
            "https://two.example.test", make_card("Two", "https://two.example.test")
        )
        first, second = submit(), submit("https://two.example.test")
        review(client, first["id"], "approve")

        approved = client.get(
            "/registry/agents?status=approved", headers=as_user(ADMIN_EMAIL)
        ).json()
        pending = client.get(
            "/registry/agents?status=pending", headers=as_user(ADMIN_EMAIL)
        ).json()
        assert [a["id"] for a in approved] == [first["id"]]
        assert [a["id"] for a in pending] == [second["id"]]

    def test_unknown_id_is_not_found(self, client: TestClient) -> None:
        assert client.get("/registry/agents/nope", headers=as_user()).status_code == 404

    def test_chris_himself_is_not_listed_or_reviewable(
        self, client: TestClient, db
    ) -> None:
        from app.models import Agent

        db.add(
            Agent(
                id="chris",
                name="Chris",
                endpoint_url="/chris/message",
                status="approved",
            )
        )
        db.commit()
        assert client.get("/registry/agents", headers=as_user(ADMIN_EMAIL)).json() == []
        assert review(client, "chris", "revoke").status_code == 404


class TestReview:
    def test_only_admins_can_review(self, client: TestClient, submit) -> None:
        agent = submit()
        response = client.post(
            f"/registry/agents/{agent['id']}/review",
            json={"action": "approve"},
            headers=as_user(USER_EMAIL),
        )
        assert response.status_code == 403

    def test_submitter_cannot_approve_their_own_agent(
        self, client: TestClient, submit
    ) -> None:
        agent = submit()
        client.post(
            f"/registry/agents/{agent['id']}/review",
            json={"action": "approve"},
            headers=as_user(USER_EMAIL),
        )
        still = client.get(
            f"/registry/agents/{agent['id']}", headers=as_user(USER_EMAIL)
        ).json()
        assert still["status"] == "pending"

    def test_approve_makes_the_agent_active_and_records_the_reviewer(
        self, client: TestClient, submit
    ) -> None:
        agent = submit()
        result = review(client, agent["id"], "approve", note="ok").json()
        assert result["status"] == "approved"
        assert result["is_active"] is True
        assert result["reviewed_by"] == ADMIN_EMAIL
        assert result["reviewed_at"] is not None
        assert result["review_note"] == "ok"

    def test_provisional_is_active(self, client: TestClient, submit) -> None:
        result = review(client, submit()["id"], "provisional").json()
        assert (result["status"], result["is_active"]) == ("provisional", True)

    @pytest.mark.parametrize("action", ["revoke", "reject"])
    def test_revoke_and_reject_make_the_agent_inactive(
        self, client: TestClient, submit, action: str
    ) -> None:
        result = review(client, submit()["id"], action).json()
        assert (result["status"], result["is_active"]) == ("revoked", False)

    def test_admin_can_set_tier_role_and_featured(
        self, client: TestClient, submit
    ) -> None:
        result = review(
            client,
            submit()["id"],
            "approve",
            trust_tier="authenticated",
            required_role="student",
            is_featured=True,
        ).json()
        assert result["trust_tier"] == "authenticated"
        assert result["required_role"] == "student"
        assert result["is_featured"] is True

    def test_review_without_tier_keeps_the_existing_tier(
        self, client: TestClient, submit
    ) -> None:
        agent = submit()
        review(client, agent["id"], "approve", trust_tier="privileged")
        assert (
            review(client, agent["id"], "provisional").json()["trust_tier"]
            == "privileged"
        )

    def test_unknown_agent_is_not_found(self, client: TestClient) -> None:
        assert review(client, "nope", "approve").status_code == 404

    @pytest.mark.parametrize(
        "body",
        [
            {"action": "delete"},
            {"action": "approve", "trust_tier": "root"},
            {"action": "approve", "status": "approved"},
            {},
        ],
    )
    def test_invalid_review_bodies_are_rejected(
        self, client: TestClient, submit, body: dict
    ) -> None:
        response = client.post(
            f"/registry/agents/{submit()['id']}/review",
            json=body,
            headers=as_user(ADMIN_EMAIL),
        )
        assert response.status_code == 422
