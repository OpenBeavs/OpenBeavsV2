"""Chris HTTP routes.

POST /chris/message: route a message to an agent, or answer it directly.
Kept thin; model access lives in ``llm.py`` and routing in ``agent_selection.py``.
"""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.chris.agent_selection import choose_agent
from app.chris.agents import MOCK_AGENTS, Agent
from app.chris.llm import LLMError, generate
from app.chris.prompts import build_direct_prompt
from app.chris.sessions import (
    chat_principal,
    load_history,
    persist_turn,
    prepare_conversation,
    purge_expired_chats,
)
from app.config import ConfigError, env_flag
from app.db import get_db
from app.registry.auth import Principal, require_admin
from app.registry.service import routable_agents

log = logging.getLogger(__name__)

router = APIRouter()


class HistoryMessage(BaseModel):
    """One earlier turn in the conversation."""

    role: Literal["user", "assistant"]
    content: str


class ChrisMessageForm(BaseModel):
    """Request body for POST /chris/message."""

    message: str
    history: list[HistoryMessage] = []
    chat_id: str | None = None
    user_id: str | None = None
    guest_session_id: str | None = None
    source_domain: str | None = None


class ChrisMessageResponse(BaseModel):
    """Response body.

    ``routed_to`` and ``agent_name`` are set when Chris picked an agent. The
    ``routing_*`` fields show the model's decision (when routing ran), which
    helps tune routing even when the answer came directly from Chris.
    """

    response: str
    chat_id: str | None = None
    guest_session_id: str | None = None
    routed_to: str | None = None
    agent_name: str | None = None
    routing_confidence: float | None = None
    routing_reason: str | None = None


class AgentSummary(BaseModel):
    """Public summary of an active registered agent."""

    id: str
    name: str
    description: str | None = None
    endpoint_url: str
    card_url: str | None = None
    trust_tier: str
    required_role: str | None = None
    skills: list[Any] | None = None
    capabilities: dict[str, Any] | None = None
    is_featured: bool = False


def _extract_skills(raw_skills: Any) -> list[str]:
    """Extract list of skill strings/tags from database JSON."""
    if not raw_skills:
        return []
    if isinstance(raw_skills, list):
        result = []
        for s in raw_skills:
            if isinstance(s, str):
                result.append(s)
            elif isinstance(s, dict):
                if "name" in s and isinstance(s["name"], str):
                    result.append(s["name"])
                if "tags" in s and isinstance(s["tags"], list):
                    result.extend(t for t in s["tags"] if isinstance(t, str))
        return result
    return []


def _installed_agents(db: Session) -> list[Agent]:
    """Return the agents Chris can route to.

    Uses MOCK_AGENTS if CHRIS_USE_MOCK_AGENTS is set. Otherwise, queries the
    registry for active agents an admin has approved (or marked provisional).
    Pending and revoked agents are never routable.
    """
    if env_flag("CHRIS_USE_MOCK_AGENTS"):
        return MOCK_AGENTS

    try:
        db_agents = routable_agents(db)
    except SQLAlchemyError:
        db.rollback()
        log.error("Agent lookup failed; no external agents will be offered.")
        return []

    return [
        Agent(
            id=a.id,
            name=a.name,
            description=a.description or "",
            skills=_extract_skills(a.skills),
        )
        for a in db_agents
    ]


@router.post("/message", response_model=ChrisMessageResponse)
async def chris_message(
    form: ChrisMessageForm,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[Principal | None, Depends(chat_principal)],
) -> ChrisMessageResponse:
    """Authorize, select a candidate or answer directly, and save the turn.

    Expert dispatch is still a prototype: selection returns a Chris-authored
    acknowledgement, never an invented answer attributed to an expert.
    """
    message = form.message.strip()
    if not message:
        raise HTTPException(400, "Message cannot be empty.")
    try:
        conversation = prepare_conversation(
            db, form.chat_id, form.user_id, form.guest_session_id, principal
        )
        history = (
            load_history(db, conversation)
            if conversation.existing
            else [{"role": m.role, "content": m.content} for m in form.history]
        )
    except SQLAlchemyError:
        db.rollback()
        # Never substitute client history if ownership or stored history cannot be checked.
        raise HTTPException(503, "Conversation storage unavailable.") from None

    agents = _installed_agents(db)
    try:
        selection = await choose_agent(message, agents)
        if selection.agent:
            reply = f"Chris would route this to {selection.agent.name}. Calling agents is not implemented yet."
        else:
            reply = await generate(
                [
                    {"role": "system", "content": build_direct_prompt(agents)},
                    *history,
                    {"role": "user", "content": message},
                ]
            )
    except ConfigError as e:
        log.error("Chris configuration error: %s", e)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from e
    except LLMError:
        log.error("Chris model call failed.")
        raise HTTPException(
            503, "Chris is temporarily unavailable. Please try again shortly."
        ) from None

    routed_id = selection.agent.id if selection.agent else None
    chat_id = persist_turn(
        db,
        conversation,
        principal,
        message,
        reply,
        routed_id,
        form.source_domain,
        {
            "routing_confidence": selection.confidence,
            "routing_reason": selection.reason,
            "selected_agent_id": routed_id,
        },
    )
    return ChrisMessageResponse(
        response=reply,
        chat_id=chat_id,
        guest_session_id=conversation.guest_token if chat_id else None,
        routed_to=routed_id,
        agent_name=selection.agent.name if selection.agent else None,
        routing_confidence=selection.confidence,
        routing_reason=selection.reason,
    )


@router.get("/agents", response_model=list[AgentSummary])
def list_active_agents(db: Annotated[Session, Depends(get_db)]) -> list[dict[str, Any]]:
    """List the active, reviewed agents Chris can route to."""
    db_agents = routable_agents(db)
    return [
        {
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "endpoint_url": a.endpoint_url,
            "card_url": a.card_url,
            "trust_tier": a.trust_tier,
            "required_role": a.required_role,
            "skills": a.skills,
            "capabilities": a.capabilities,
            "is_featured": a.is_featured,
        }
        for a in db_agents
    ]


@router.delete("/chats/expired")
def delete_expired_chats(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Principal, Depends(require_admin)],
) -> dict[str, int]:
    """Explicitly authorized maintenance; scheduling is a deployment responsibility."""
    return {"purged": purge_expired_chats(db)}


@router.get("/.well-known/agent.json")
def chris_agent_card() -> None:
    """Do not advertise the prototype JSON endpoint as an A2A transport."""
    raise HTTPException(
        501, "Chris A2A discovery is unavailable until an A2A transport is implemented."
    )
