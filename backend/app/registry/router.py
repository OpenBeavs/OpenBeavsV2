"""Registry HTTP routes (mounted at ``/registry``).

POST /registry/agents              submit an agent by URL (becomes ``pending``)
GET  /registry/agents              list the entries the caller may see
GET  /registry/agents/{id}         one entry
POST /registry/agents/{id}/review  admin decision: approve / provisional / revoke / reject

Kept thin: fetching and validation live in ``cards.py``, database logic in
``service.py``.
"""

import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import env_flag
from app.db import get_db
from app.models import Agent
from app.registry import service
from app.registry.auth import Principal, current_principal, require_admin
from app.registry.cards import AgentCard, CardError, fetch_card
from app.registry.schemas import RegistryAgentOut, ReviewForm, SubmitAgentForm
from app.registry.security import UnsafeURLError

log = logging.getLogger(__name__)

router = APIRouter()

CardFetcher = Callable[[str], AgentCard]


def get_card_fetcher() -> CardFetcher:
    """Return the function that fetches a card (replaced in tests)."""
    allow_http = env_flag("REGISTRY_ALLOW_HTTP")
    return lambda url: fetch_card(url, allow_http=allow_http)


def _to_out(agent: Agent, principal: Principal) -> RegistryAgentOut:
    """Convert a row to its response, hiding submitter and review details."""
    out = RegistryAgentOut.model_validate(agent)
    if not (principal.is_admin or agent.submitted_by == principal.email):
        out.submitted_by = None
        out.reviewed_by = None
        out.reviewed_at = None
        out.review_note = None
    return out


@router.post(
    "/agents", response_model=RegistryAgentOut, status_code=status.HTTP_201_CREATED
)
def submit_agent(
    form: SubmitAgentForm,
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[Session, Depends(get_db)],
    fetch: Annotated[CardFetcher, Depends(get_card_fetcher)],
) -> RegistryAgentOut:
    """Submit an agent by URL. It stays ``pending`` until an admin approves it."""
    try:
        card = fetch(form.url)
    except (UnsafeURLError, CardError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    try:
        agent = service.submit_agent(db, card, submitted_by=principal.email)
    except service.DuplicateAgentError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    log.info("Agent %s submitted by %s (pending review)", agent.id, principal.email)
    return _to_out(agent, principal)


@router.get("/agents", response_model=list[RegistryAgentOut])
def list_agents(
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[RegistryAgentOut]:
    """List registry entries visible to the caller, optionally filtered by status."""
    agents = service.list_visible(db, principal, status=status_filter)
    return [_to_out(a, principal) for a in agents]


@router.get("/agents/{agent_id}", response_model=RegistryAgentOut)
def get_agent(
    agent_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> RegistryAgentOut:
    """Return one registry entry, or 404 if it does not exist or is not visible."""
    agent = service.get_visible(db, agent_id, principal)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return _to_out(agent, principal)


@router.post("/agents/{agent_id}/review", response_model=RegistryAgentOut)
def review_agent(
    agent_id: str,
    form: ReviewForm,
    admin: Annotated[Principal, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> RegistryAgentOut:
    """Record an admin decision. Only approved or provisional agents are routable."""
    agent = db.get(Agent, agent_id)
    if agent is None or agent.id == service.CHRIS_AGENT_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    agent = service.review_agent(db, agent, admin, form)
    log.info("Agent %s %s by %s", agent.id, form.action, admin.email)
    return _to_out(agent, admin)
