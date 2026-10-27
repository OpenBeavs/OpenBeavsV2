"""Registry business logic: submit, list, review, and what Chris may route to.

Routers stay thin and call these functions; all database access lives here.
"""

import time
import uuid

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Agent
from app.registry.auth import Principal
from app.registry.cards import AgentCard
from app.registry.schemas import ReviewForm

# Statuses whose agents Chris may route to and everyone may see.
ROUTABLE_STATUSES = ("approved", "provisional")
CHRIS_AGENT_ID = "chris"


class DuplicateAgentError(ValueError):
    """Raised when an agent with the same card URL is already registered."""


def routable_agents(db: Session) -> list[Agent]:
    """Return the active agents Chris may route to (approved or provisional).

    Pending and revoked agents are excluded, as is Chris himself. Until real
    caller authorization exists, only public agents without a role are eligible.
    """
    stmt = select(Agent).where(
        Agent.is_active.is_(True),
        Agent.status.in_(ROUTABLE_STATUSES),
        Agent.id != CHRIS_AGENT_ID,
        Agent.trust_tier == "public",
        Agent.required_role.is_(None),
    )
    return list(db.scalars(stmt))


def has_any_agents(db: Session) -> bool:
    """Return True if the agents table has at least one row of any status."""
    return db.scalar(select(Agent.id).limit(1)) is not None


def submit_agent(db: Session, card: AgentCard, submitted_by: str) -> Agent:
    """Store a newly submitted agent as ``pending`` (never routable until reviewed).

    The trust tier is always ``public`` here; only an admin review can change it.

    Raises:
        DuplicateAgentError: If the card URL is already registered.
    """
    existing = db.scalar(select(Agent).where(Agent.card_url == card.card_url))
    if existing is not None:
        raise DuplicateAgentError("An agent with this card URL is already registered.")

    now = int(time.time())
    agent = Agent(
        id=str(uuid.uuid4()),
        name=card.name,
        description=card.description,
        endpoint_url=card.endpoint_url,
        card_url=card.card_url,
        trust_tier="public",
        skills=card.skills,
        capabilities=card.capabilities,
        is_active=False,
        is_featured=False,
        status="pending",
        submitted_by=submitted_by,
        review_note=" ".join(card.flags) or None,
        created_at=now,
        updated_at=now,
    )
    db.add(agent)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateAgentError(
            "An agent with this card URL is already registered."
        ) from exc
    return agent


def list_visible(
    db: Session, principal: Principal, status: str | None = None
) -> list[Agent]:
    """Return the registry entries ``principal`` may see.

    Admins see everything. Everyone else sees approved and provisional agents plus
    their own submissions in any status.
    """
    stmt = select(Agent).where(Agent.id != CHRIS_AGENT_ID).order_by(Agent.created_at)
    if not principal.is_admin:
        stmt = stmt.where(
            or_(
                (Agent.is_active.is_(True)) & Agent.status.in_(ROUTABLE_STATUSES),
                Agent.submitted_by == principal.email,
            )
        )
    if status:
        stmt = stmt.where(Agent.status == status)
    return list(db.scalars(stmt))


def get_visible(db: Session, agent_id: str, principal: Principal) -> Agent | None:
    """Return one entry if ``principal`` may see it, otherwise None."""
    agent = db.get(Agent, agent_id)
    if agent is None or agent.id == CHRIS_AGENT_ID:
        return None
    if principal.is_admin or agent.submitted_by == principal.email:
        return agent
    if agent.is_active and agent.status in ROUTABLE_STATUSES:
        return agent
    return None


def review_agent(
    db: Session, agent: Agent, reviewer: Principal, form: ReviewForm
) -> Agent:
    """Apply an admin decision and record who made it and when."""
    if form.action == "approve":
        agent.status, agent.is_active = "approved", True
    elif form.action == "provisional":
        agent.status, agent.is_active = "provisional", True
    else:  # "revoke" and "reject" both leave the agent unroutable
        agent.status, agent.is_active = "revoked", False

    if form.trust_tier is not None:
        agent.trust_tier = form.trust_tier
    if form.required_role is not None:
        agent.required_role = form.required_role
    if form.is_featured is not None:
        agent.is_featured = form.is_featured

    now = int(time.time())
    agent.reviewed_by = reviewer.email
    agent.reviewed_at = now
    agent.updated_at = now
    if form.note is not None:
        agent.review_note = form.note
    db.commit()
    return agent
