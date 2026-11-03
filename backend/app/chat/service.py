"""Chat application workflow: authorize, load history, ask Chris, and persist turns.

The existing ordering and database failure fallbacks are preserved. Agent selection
and model access remain in Chris; this module owns the application's chat state.
"""

import logging
import time
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.chat.schemas import ChrisMessageForm, ChrisMessageResponse
from app.chris.agent_selection import choose_agent
from app.chris.agents import MOCK_AGENTS, Agent
from app.chris.llm import LLMError
from app.chris.service import answer_direct
from app.config import ConfigError, env_flag
from app.models import Chat as DBChat
from app.models import Message as DBMessage
from app.models import User as DBUser
from app.registry.service import routable_agents

log = logging.getLogger(__name__)

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
    Pending and revoked agents are never routable. If the table is empty or
    the query fails, returns an empty list so Chris answers directly.
    """
    if env_flag("CHRIS_USE_MOCK_AGENTS"):
        return MOCK_AGENTS

    try:
        db_agents = routable_agents(db)
    except SQLAlchemyError as e:
        log.error("Failed to query installed agents from database: %s", e)
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


def purge_expired_chats(db: Session) -> int:
    """Delete expired guest chats whose TTL has elapsed.

    Returns the number of deleted chats.
    """
    now = int(time.time())
    try:
        expired_chats = (
            db.query(DBChat)
            .filter(DBChat.expires_at.isnot(None), DBChat.expires_at <= now)
            .all()
        )
        count = len(expired_chats)
        for chat in expired_chats:
            db.delete(chat)
        if count:
            db.commit()
        return count
    except SQLAlchemyError as e:
        db.rollback()
        log.error("Failed to purge expired chats: %s", e)
        return 0


def _persist_turn(
    db: Session,
    form: ChrisMessageForm,
    user_text: str,
    response_text: str,
    routed_agent_id: str | None,
    meta: dict[str, Any] | None = None,
) -> str | None:
    """Save or update chat session and record user/agent turns.

    Catches database errors, logs them, and returns None so the response
    can still be delivered even if persistence fails.
    """
    try:
        now = int(time.time())
        now_ms = int(time.time() * 1000)
        chat_id = form.chat_id or str(uuid.uuid4())

        chat = db.get(DBChat, chat_id)
        if not chat:
            # Only treat as authenticated if a verified user exists in the database
            verified_user = db.get(DBUser, form.user_id) if form.user_id else None
            if verified_user:
                session_type = "authenticated"
                user_id = verified_user.id
                expires_at = None
            else:
                session_type = "guest"
                user_id = None
                # 2-hour TTL for guest/anonymous sessions
                # Note: TTL cleanup is enforced by purge_expired_chats()
                expires_at = now + 7200

            chat = DBChat(
                id=chat_id,
                user_id=user_id,
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
            created_at=now_ms,
        )
        # Record Assistant Message with distinct, increasing timestamp
        agent_msg = DBMessage(
            chat_id=chat_id,
            sender_type="agent",
            content=response_text,
            meta=meta,
            created_at=now_ms + 1,
        )
        db.add_all([user_msg, agent_msg])
        db.commit()
        return chat_id
    except SQLAlchemyError as e:
        db.rollback()
        log.error("Failed to persist chat turn to database: %s", e)
        return None


async def handle_message(
    form: ChrisMessageForm,
    db: Session,
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

    # Object-level authorization check: prevent unauthorized access or turn injection (IDOR)
    if form.chat_id:
        existing_chat = db.get(DBChat, form.chat_id)
        if existing_chat:
            is_authorized = False
            if existing_chat.user_id:
                # Authenticated session: caller must be the verified owner
                verified_user = db.get(DBUser, form.user_id) if form.user_id else None
                if verified_user and verified_user.id == existing_chat.user_id:
                    is_authorized = True
            elif existing_chat.guest_session_id:
                # Guest session: caller must provide matching guest token
                if (
                    form.guest_session_id
                    and form.guest_session_id == existing_chat.guest_session_id
                ):
                    is_authorized = True
            else:
                is_authorized = True

            if not is_authorized:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: You are not authorized to access or modify this chat session.",
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

        # Single source of truth for history: load from DB if chat_id exists,
        # otherwise use client-provided history.
        if form.chat_id:
            try:
                stored_messages = (
                    db.query(DBMessage)
                    .filter(DBMessage.chat_id == form.chat_id)
                    .order_by(DBMessage.created_at.asc())
                    .all()
                )
                history_entries = [
                    {
                        "role": "assistant"
                        if m.sender_type == "agent"
                        else m.sender_type,
                        "content": m.content,
                    }
                    for m in stored_messages
                    if m.sender_type in ("user", "agent", "assistant")
                ]
            except SQLAlchemyError as e:
                log.warning(
                    "Could not load stored history for chat %s: %s", form.chat_id, e
                )
                history_entries = [
                    {"role": m.role, "content": m.content} for m in form.history
                ]
        else:
            history_entries = [
                {"role": m.role, "content": m.content} for m in form.history
            ]

        reply = await answer_direct(message, history_entries, agents)

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

    # Persist turn outside LLM try block; catch DB errors without failing response
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

    return ChrisMessageResponse(
        response=reply,
        chat_id=chat_id,
        routing_confidence=selection.confidence,
        routing_reason=selection.reason,
    )


def list_active_agents(db: Session) -> list[dict[str, Any]]:
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
