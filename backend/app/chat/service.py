"""Chat application workflow: authorize, load history, ask Chris, and persist turns.

Chris is called over A2A; this module owns the application's chat state.
"""

import logging
import time
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.chat.a2a_client import ChrisUnavailable, send_message
from app.chat.schemas import ChrisMessageForm, ChrisMessageResponse
from app.config import ConfigError
from app.history import MAX_HISTORY_TURNS, bounded_history
from app.models import Agent as DBAgent
from app.models import Chat as DBChat
from app.models import Message as DBMessage
from app.models import User as DBUser
from app.registry.service import routable_agents

log = logging.getLogger(__name__)


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
    """Authorize a chat turn, send it to Chris over A2A, and save its answer."""
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

    try:
        # Single source of truth for history: load from DB if chat_id exists,
        # otherwise use client-provided history.
        if form.chat_id:
            try:
                stored_messages = (
                    db.query(DBMessage)
                    .filter(DBMessage.chat_id == form.chat_id)
                    .order_by(DBMessage.created_at.desc(), DBMessage.id.desc())
                    .limit(MAX_HISTORY_TURNS)
                    .all()
                )
                history_entries = [
                    {
                        "role": "assistant"
                        if m.sender_type == "agent"
                        else m.sender_type,
                        "content": m.content,
                    }
                    for m in reversed(stored_messages)
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

        reply = await send_message(message, bounded_history(history_entries))

    except ConfigError as e:
        log.error("Chris configuration error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
    except ChrisUnavailable:
        log.warning("Chris A2A call did not produce a completed answer.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chris is temporarily unavailable. Please try again shortly.",
        )

    routing, text = reply.routing, reply.text
    if routing is not None and routing.status == "selected" and routing.agent:
        # Chris reports only the selected agent's id; the display name and description
        # come from this application's own agents table.
        try:
            record = db.get(DBAgent, routing.agent.id)
        except SQLAlchemyError:
            db.rollback()
            log.warning("Could not load selected expert display details.")
            record = None
        if record is not None:
            routing.agent.name = record.name
            routing.agent.description = record.description
            text = (
                f"The registry selected {record.name} for this question. "
                "No expert has been called yet, so this is not an answer."
            )
    # Persist after A2A succeeds; catch DB errors without failing the response.
    # The decision is kept in the message's meta. ``chats.agent_id`` is not set: a
    # selection is not a conversation with that expert (none has been called), and the
    # selected id comes from the registry's database, not necessarily this one.
    chat_id = _persist_turn(
        db,
        form,
        message,
        text,
        routed_agent_id=None,
        meta={"routing": routing.model_dump()} if routing else None,
    )

    selected = routing is not None and routing.status == "selected" and routing.agent
    return ChrisMessageResponse(
        response=text,
        chat_id=chat_id,
        routing=routing,
        routed_to=routing.agent.id if selected else None,
        agent_name=routing.agent.name if selected else None,
    )


def list_active_agents(db: Session) -> list[dict[str, Any]]:
    """List active, reviewed agents for the frontend directory."""
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
