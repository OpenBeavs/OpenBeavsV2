"""Chris HTTP routes.

POST /chris/message: route a message to an agent, or answer it directly.
Kept thin; model access lives in ``llm.py`` and routing in ``agent_selection.py``.
"""

import logging
import time
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.chris.agent_selection import choose_agent
from app.chris.agents import MOCK_AGENTS, Agent
from app.chris.llm import LLMError, generate
from app.chris.prompts import build_direct_prompt
from app.config import ConfigError, env_flag
from app.db import get_db
from app.models import Agent as DBAgent
from app.models import Chat as DBChat
from app.models import Message as DBMessage

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

    Uses MOCK_AGENTS if CHRIS_USE_MOCK_AGENTS is set. Otherwise, queries
    all active agents from the database.
    """
    if env_flag("CHRIS_USE_MOCK_AGENTS"):
        return MOCK_AGENTS

    db_agents = (
        db.query(DBAgent)
        .filter(DBAgent.is_active.is_(True), DBAgent.id != "chris")
        .all()
    )
    if not db_agents:
        # Fallback to mock list if database is empty
        return MOCK_AGENTS

    return [
        Agent(
            id=a.id,
            name=a.name,
            description=a.description or "",
            skills=_extract_skills(a.skills),
        )
        for a in db_agents
    ]


def _persist_turn(
    db: Session,
    form: ChrisMessageForm,
    user_text: str,
    response_text: str,
    routed_agent_id: str | None,
    meta: dict[str, Any] | None = None,
) -> str:
    """Save or update chat session and record user/agent turns."""
    now = int(time.time())
    chat_id = form.chat_id or str(uuid.uuid4())

    chat = db.get(DBChat, chat_id)
    if not chat:
        # 2-hour TTL for guest/anonymous sessions
        expires_at = now + 7200 if not form.user_id else None
        session_type = "authenticated" if form.user_id else "guest"
        chat = DBChat(
            id=chat_id,
            user_id=form.user_id,
            guest_session_id=form.guest_session_id,
            agent_id=routed_agent_id,
            title=user_text[:50] if len(user_text) > 50 else user_text,
            source_domain=form.source_domain,
            session_type=session_type,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )
        db.add(chat)
    else:
        chat.updated_at = now
        if routed_agent_id:
            chat.agent_id = routed_agent_id

    # Record User Message
    user_msg = DBMessage(
        chat_id=chat_id,
        sender_type="user",
        content=user_text,
        created_at=now,
    )
    # Record Assistant Message
    agent_msg = DBMessage(
        chat_id=chat_id,
        sender_type="agent",
        content=response_text,
        meta=meta,
        created_at=now,
    )
    db.add_all([user_msg, agent_msg])
    db.commit()
    return chat_id


@router.post("/message", response_model=ChrisMessageResponse)
async def chris_message(
    form: ChrisMessageForm,
    db: Annotated[Session, Depends(get_db)],
) -> ChrisMessageResponse:
    """Route a message to an agent or answer it directly via the configured model.

    Agent calling is not implemented yet: when an agent is chosen, the reply
    says so instead of calling it.
    """
    message = form.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty."
        )

    agents = _installed_agents(db)

    try:
        selection = await choose_agent(message, agents)

        if selection.agent:
            response_text = (
                f"Chris would route this to {selection.agent.name}. "
                "Calling agents is not implemented yet."
            )
            chat_id = _persist_turn(
                db,
                form,
                message,
                response_text,
                routed_agent_id=selection.agent.id,
                meta={
                    "routing_confidence": selection.confidence,
                    "routing_reason": selection.reason,
                },
            )
            return ChrisMessageResponse(
                response=response_text,
                chat_id=chat_id,
                routed_to=selection.agent.id,
                agent_name=selection.agent.name,
                routing_confidence=selection.confidence,
                routing_reason=selection.reason,
            )

        messages = [
            {"role": "system", "content": build_direct_prompt(agents)},
            *({"role": m.role, "content": m.content} for m in form.history),
            {"role": "user", "content": message},
        ]
        reply = await generate(messages)

        chat_id = _persist_turn(
            db,
            form,
            message,
            reply,
            routed_agent_id=None,
            meta={
                "routing_confidence": selection.confidence,
                "routing_reason": selection.reason,
            },
        )
    except ConfigError as e:
        log.error("Chris configuration error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
    except LLMError as e:
        log.error("Chris model call failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chris is temporarily unavailable. Please try again shortly.",
        )

    return ChrisMessageResponse(
        response=reply,
        chat_id=chat_id,
        routing_confidence=selection.confidence,
        routing_reason=selection.reason,
    )


@router.get("/agents", response_model=list[AgentSummary])
def list_active_agents(db: Annotated[Session, Depends(get_db)]) -> list[dict[str, Any]]:
    """List all active external agents registered for Chris routing."""
    db_agents = (
        db.query(DBAgent)
        .filter(DBAgent.is_active.is_(True), DBAgent.id != "chris")
        .all()
    )
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
