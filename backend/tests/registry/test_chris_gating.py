"""Only reviewed, eligible external agents are offered for routing."""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Agent
from app.registry.service import routable_agents

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


def offered_to_router(db: Session) -> list[str]:
    """Return the ids of the agents the registry offers for selection."""
    return [agent.id for agent in routable_agents(db)]

def test_only_approved_and_provisional_agents_are_offered(db: Session) -> None:
    add_agent(db, "approved", "approved")
    add_agent(db, "provisional", "provisional")
    # Active but not reviewed: only the status check keeps these out.
    add_agent(db, "pending", "pending", active=True)
    add_agent(db, "revoked", "revoked", active=True)
    # Inactive as well, the state the registry itself creates.
    add_agent(db, "pending-off", "pending", active=False)
    add_agent(db, "revoked-off", "revoked", active=False)

    assert sorted(offered_to_router(db)) == ["approved", "provisional"]


def test_an_inactive_approved_agent_is_not_offered(db: Session) -> None:
    add_agent(db, "paused", "approved", active=False)
    add_agent(db, "live", "approved")
    assert offered_to_router(db) == ["live"]


def test_privileged_and_role_gated_agents_are_not_offered(db: Session) -> None:
    add_agent(db, "live", "approved")
    add_agent(db, "admin-only", "approved")
    add_agent(db, "faculty-only", "approved")
    db.get(Agent, "admin-only").trust_tier = "privileged"
    db.get(Agent, "faculty-only").required_role = "faculty"
    db.commit()
    assert offered_to_router(db) == ["live"]


def test_chris_is_never_offered_to_himself(db: Session) -> None:
    add_agent(db, "chris", "approved")
    add_agent(db, "live", "approved")
    assert offered_to_router(db) == ["live"]


def test_empty_table_does_not_enable_mock_agents(db: Session) -> None:
    assert offered_to_router(db) == []


def test_revoking_every_agent_does_not_bring_back_the_mock_agents(db: Session) -> None:
    add_agent(db, "only", "revoked", active=True)
    assert offered_to_router(db) == []


def test_submitted_agent_becomes_routable_only_after_approval(
    client: TestClient, submit, db: Session
) -> None:
    """The whole path: submit -> pending (not offered) -> approve (offered)."""
    agent = submit()
    add_agent(db, "other", "approved")

    assert offered_to_router(db) == ["other"]

    client.post(
        f"/registry/agents/{agent['id']}/review",
        json={"action": "approve"},
        headers=as_user(ADMIN_EMAIL),
    )
    assert sorted(offered_to_router(db)) == sorted([agent["id"], "other"])

    client.post(
        f"/registry/agents/{agent['id']}/review",
        json={"action": "revoke"},
        headers=as_user(ADMIN_EMAIL),
    )
    assert offered_to_router(db) == ["other"]
