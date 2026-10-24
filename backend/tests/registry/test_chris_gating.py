"""Chris routes only to agents an admin has reviewed.

These tests replace the model calls (as the team's other Chris tests do) and
inspect which agents Chris offers to the router.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.chris.agent_selection import Selection
from app.chris.agents import MOCK_AGENTS
from app.models import Agent

from .conftest import ADMIN_EMAIL, as_user


def add_agent(db: Session, agent_id: str, status: str, active: bool = True) -> None:
    """Insert an agent row directly with the given review status."""
    db.add(
        Agent(
            id=agent_id,
            name=agent_id.title(),
            description=f"The {agent_id} agent.",
            endpoint_url=f"https://{agent_id}.example.test/",
            card_url=f"https://{agent_id}.example.test/.well-known/agent.json",
            skills=["x"],
            is_active=active,
            status=status,
        )
    )
    db.commit()


def offered_to_router(client: TestClient) -> list[str]:
    """Send one message and return the agent ids Chris offered to the router."""
    with (
        patch("app.chris.router.choose_agent", new_callable=AsyncMock) as choose,
        patch("app.chris.router.generate", new_callable=AsyncMock) as generate,
    ):
        choose.return_value = Selection()
        generate.return_value = "Hello."
        response = client.post("/chris/message", json={"message": "Hi"})
    assert response.status_code == 200, response.text
    return [agent.id for agent in choose.call_args.args[1]]


def test_only_approved_and_provisional_agents_are_offered(
    client: TestClient, db: Session
) -> None:
    add_agent(db, "approved", "approved")
    add_agent(db, "provisional", "provisional")
    # Active but not reviewed: only the status check keeps these out.
    add_agent(db, "pending", "pending", active=True)
    add_agent(db, "revoked", "revoked", active=True)
    # Inactive as well, the state the registry itself creates.
    add_agent(db, "pending-off", "pending", active=False)
    add_agent(db, "revoked-off", "revoked", active=False)

    assert sorted(offered_to_router(client)) == ["approved", "provisional"]


def test_an_inactive_approved_agent_is_not_offered(
    client: TestClient, db: Session
) -> None:
    add_agent(db, "paused", "approved", active=False)
    add_agent(db, "live", "approved")
    assert offered_to_router(client) == ["live"]


def test_chris_is_never_offered_to_himself(client: TestClient, db: Session) -> None:
    add_agent(db, "chris", "approved")
    add_agent(db, "live", "approved")
    assert offered_to_router(client) == ["live"]


def test_mock_agents_are_used_only_for_a_completely_empty_table(
    client: TestClient,
) -> None:
    assert offered_to_router(client) == [a.id for a in MOCK_AGENTS]


def test_revoking_every_agent_does_not_bring_back_the_mock_agents(
    client: TestClient, db: Session
) -> None:
    add_agent(db, "only", "revoked", active=True)
    assert offered_to_router(client) == []


def test_mock_flag_still_forces_the_mock_list(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_agent(db, "real", "approved")
    monkeypatch.setenv("CHRIS_USE_MOCK_AGENTS", "true")
    assert offered_to_router(client) == [a.id for a in MOCK_AGENTS]


def test_agents_endpoint_lists_only_routable_agents(
    client: TestClient, db: Session
) -> None:
    add_agent(db, "approved", "approved")
    add_agent(db, "pending", "pending", active=True)
    listed = client.get("/chris/agents").json()
    assert [a["id"] for a in listed] == ["approved"]


def test_submitted_agent_becomes_routable_only_after_approval(
    client: TestClient, submit, db: Session
) -> None:
    """The whole path: submit -> pending (not offered) -> approve (offered)."""
    agent = submit()
    add_agent(db, "other", "approved")

    assert offered_to_router(client) == ["other"]

    client.post(
        f"/registry/agents/{agent['id']}/review",
        json={"action": "approve"},
        headers=as_user(ADMIN_EMAIL),
    )
    assert sorted(offered_to_router(client)) == sorted([agent["id"], "other"])

    client.post(
        f"/registry/agents/{agent['id']}/review",
        json={"action": "revoke"},
        headers=as_user(ADMIN_EMAIL),
    )
    assert offered_to_router(client) == ["other"]
