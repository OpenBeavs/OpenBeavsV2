"""Conversation ownership and persistence. No request-body identity is trusted."""

import hashlib
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Agent, Chat, Message, User
from app.registry.auth import Principal, current_principal

log = logging.getLogger(__name__)


def chat_principal(
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_email: Annotated[str | None, Header()] = None,
) -> Principal | None:
    """Optional identity seam; header auth is explicitly local-dev only.

    Replace with verified SSO identity in production. With no headers, callers
    are guests. Headers fail closed unless existing dev auth is enabled.
    """
    if x_user_id is None and x_user_email is None:
        return None
    return current_principal(x_user_id, x_user_email)


def token_digest(token: str) -> str:
    """Store only a one-way digest of the guest bearer credential."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Conversation:
    """Authorized context carried from preflight to the atomic write."""

    chat_id: str
    user_id: str | None
    guest_token: str | None
    existing: bool


def authorize(chat: Chat, principal: Principal | None, token: str | None) -> None:
    """Require verified ownership, then reject expired conversations."""
    if chat.user_id:
        allowed = principal is not None and principal.id == chat.user_id
    else:
        allowed = bool(
            token
            and chat.guest_session_id
            and secrets.compare_digest(token_digest(token), chat.guest_session_id)
        )
    if not allowed:
        raise HTTPException(403, "Access denied to this conversation.")
    if chat.expires_at is not None and chat.expires_at <= int(time.time()):
        raise HTTPException(410, "Conversation expired. Start a new conversation.")


def prepare_conversation(
    db: Session,
    chat_id: str | None,
    claimed_user: str | None,
    token: str | None,
    principal: Principal | None,
) -> Conversation:
    """Authenticate before loading history or invoking any model."""
    if claimed_user and (principal is None or claimed_user != principal.id):
        raise HTTPException(403, "Request-body user_id is not authentication.")
    if principal and db.get(User, principal.id) is None:
        raise HTTPException(403, "Authenticated user has not been provisioned.")
    if chat_id:
        chat = db.get(Chat, chat_id)
        if chat is None:
            raise HTTPException(404, "Conversation not found.")
        authorize(chat, principal, token)
        return Conversation(
            chat.id, chat.user_id, token if not chat.user_id else None, True
        )
    # Do not accept a client-selected session credential or chat identifier.
    return Conversation(
        str(uuid.uuid4()),
        principal.id if principal else None,
        None if principal else secrets.token_urlsafe(32),
        False,
    )


def load_history(db: Session, conversation: Conversation) -> list[dict[str, str]]:
    """Read ordered history only after the caller has authorized the chat."""
    rows = db.scalars(
        select(Message)
        .where(Message.chat_id == conversation.chat_id)
        .order_by(Message.sequence)
    ).all()
    return [
        {
            "role": "assistant" if m.sender_type == "agent" else m.sender_type,
            "content": m.content,
        }
        for m in rows
        if m.sender_type in ("user", "assistant", "agent")
    ]


def persist_turn(
    db: Session,
    conversation: Conversation,
    principal: Principal | None,
    user_text: str,
    response_text: str,
    routed_agent_id: str | None,
    source_domain: str | None,
    meta: dict,
    responding_agent_id: str | None = None,
) -> str | None:
    """Append atomically; PostgreSQL row locking serializes sequence allocation.

    A unique constraint prevents duplicate positions on SQLite too. A failed
    write returns None so the caller knows the answer was not saved.
    The current routing placeholder is written by Chris, not the chosen expert.
    """
    try:
        now = int(time.time())
        if conversation.existing:
            chat = db.scalar(
                select(Chat)
                .where(Chat.id == conversation.chat_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if chat is None:
                raise HTTPException(404, "Conversation no longer exists.")
            authorize(chat, principal, conversation.guest_token)
        else:
            chat = Chat(
                id=conversation.chat_id,
                user_id=conversation.user_id,
                guest_session_id=token_digest(conversation.guest_token)
                if conversation.guest_token
                else None,
                session_type="authenticated" if conversation.user_id else "guest",
                expires_at=None if conversation.user_id else now + 7200,
                title=user_text[:50],
                source_domain=source_domain,
                created_at=now,
                updated_at=now,
            )
            db.add(chat)
            db.flush()
        # Mock IDs are never stored as foreign keys.
        chat.agent_id = (
            routed_agent_id
            if routed_agent_id and db.get(Agent, routed_agent_id)
            else None
        )
        chat.updated_at = now
        last = (
            db.scalar(
                select(func.max(Message.sequence)).where(Message.chat_id == chat.id)
            )
            or 0
        )
        db.add_all(
            [
                Message(
                    chat_id=chat.id,
                    sequence=last + 1,
                    sender_type="user",
                    content=user_text,
                    created_at=now,
                ),
                Message(
                    chat_id=chat.id,
                    sequence=last + 2,
                    sender_type="agent",
                    content=response_text,
                    agent_id=responding_agent_id,
                    meta=meta,
                    created_at=now,
                ),
            ]
        )
        db.commit()
        return chat.id
    except SQLAlchemyError:
        db.rollback()
        log.error("Conversation persistence failed; answer was not saved.")
        return None


def purge_expired_chats(db: Session) -> int:
    """Delete expired guest conversations; caller must authorize maintenance."""
    try:
        chats = db.scalars(
            select(Chat).where(
                Chat.session_type == "guest", Chat.expires_at <= int(time.time())
            )
        ).all()
        for chat in chats:
            db.delete(chat)
        db.commit()
        return len(chats)
    except SQLAlchemyError:
        db.rollback()
        log.error("Conversation cleanup failed.")
        raise HTTPException(503, "Conversation cleanup unavailable.") from None
