"""Chat workflow: stateless for guests, database-backed for signed-in callers.

Guest turns never read or write ``chats`` or ``messages``. When a request carries a
verified session user, turns are stored under that user's ownership and continued chats
load their bounded prior context from the database rather than trusting client history.
"""

import logging
import time
import uuid

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from application_services.chat.a2a_client import ChrisUnavailable, send_message
from application_services.chat.schemas import (
    ChatDetail,
    ChatMessageOut,
    ChatSummary,
    ChatUpdateForm,
    ChrisMessageForm,
    ChrisMessageResponse,
    RoutingInfo,
)
from application_services.config import ConfigError
from application_services.history import bounded_history
from application_services.models import Chat, Message
from application_services.models import User as DBUser

log = logging.getLogger(__name__)

MAX_TITLE_CHARS = 48


def _derive_title(message: str) -> str:
    """Create a readable sidebar title from the opening user prompt."""
    collapsed = " ".join(message.split())
    if not collapsed:
        return "New Conversation"
    if len(collapsed) <= MAX_TITLE_CHARS:
        return collapsed
    return f"{collapsed[: MAX_TITLE_CHARS - 1]}…"


def _clean_source_domain(source_domain: str | None) -> str | None:
    if not source_domain:
        return None
    cleaned = source_domain.strip()
    return cleaned[:255] if cleaned else None


def _get_owned_chat(db: Session, chat_id: str, caller: DBUser) -> Chat:
    """Return an authenticated chat owned by ``caller``, or raise 404."""
    chat = db.scalar(
        select(Chat).where(
            Chat.id == chat_id,
            Chat.user_id == caller.id,
            Chat.session_type == "authenticated",
        )
    )
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found.",
        )
    return chat


def _load_chat_messages(db: Session, chat_id: str) -> list[Message]:
    """Return all stored turns for ``chat_id`` in chronological order."""
    return list(
        db.scalars(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
    )


def _history_from_messages(messages: list[Message]) -> list[dict[str, str]]:
    """Convert stored Message rows into the role/content history format Chris expects."""
    history: list[dict[str, str]] = []
    for msg in messages:
        if msg.sender_type == "user":
            history.append({"role": "user", "content": msg.content})
        elif msg.sender_type in ("agent", "assistant"):
            history.append({"role": "assistant", "content": msg.content})
    return history


def _extract_routing(meta: object) -> RoutingInfo | None:
    """Safely parse persisted routing metadata without failing on legacy shapes."""
    if not isinstance(meta, dict):
        return None
    raw = meta.get("routing")
    if raw is None:
        return None
    try:
        return RoutingInfo.model_validate(raw)
    except ValidationError:
        return None


def _to_chat_summary(chat: Chat) -> ChatSummary:
    return ChatSummary(
        id=chat.id,
        title=chat.title or "New Conversation",
        agent_id=chat.agent_id,
        source_domain=chat.source_domain,
        is_pinned=bool(chat.is_pinned),
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def _to_message_out(message: Message) -> ChatMessageOut:
    role = "user" if message.sender_type == "user" else "assistant"
    routing = _extract_routing(message.meta) if role == "assistant" else None
    selected = routing is not None and routing.status == "selected" and routing.agent
    return ChatMessageOut(
        id=message.id,
        role=role,
        content=message.content,
        routed_to=routing.agent.id if selected else None,
        agent_name=routing.agent.name if selected else None,
        routing=routing,
        created_at=message.created_at,
    )


def _persist_authenticated_turn(
    db: Session,
    caller: DBUser,
    chat: Chat | None,
    message: str,
    reply_text: str,
    routing: RoutingInfo | None,
    source_domain: str | None,
    last_message_ms: int,
) -> Chat:
    """Persist a completed turn and create the parent chat when starting a new one."""
    now_sec = int(time.time())
    # Keep timestamps strictly increasing even when consecutive turns land in the same ms.
    user_ts = max(int(time.time() * 1000), last_message_ms + 1)
    agent_ts = user_ts + 1
    selected_agent_id = (
        routing.agent.id
        if routing is not None and routing.status == "selected" and routing.agent
        else None
    )

    if chat is None:
        chat = Chat(
            id=str(uuid.uuid4()),
            user_id=caller.id,
            guest_session_id=None,
            agent_id=selected_agent_id,
            title=_derive_title(message),
            source_domain=_clean_source_domain(source_domain),
            session_type="authenticated",
            is_pinned=False,
            created_at=now_sec,
            updated_at=now_sec,
            expires_at=None,
        )
        db.add(chat)
    else:
        chat.updated_at = now_sec
        if selected_agent_id:
            chat.agent_id = selected_agent_id

    user_msg = Message(
        chat_id=chat.id,
        sender_type="user",
        content=message,
        created_at=user_ts,
    )
    agent_msg = Message(
        chat_id=chat.id,
        sender_type="agent",
        content=reply_text,
        meta={"routing": routing.model_dump()} if routing is not None else None,
        created_at=agent_ts,
    )
    db.add_all([user_msg, agent_msg])

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        log.error("Failed to persist authenticated chat turn (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not save conversation. Please try again shortly.",
        ) from None
    return chat


async def handle_message(
    form: ChrisMessageForm,
    db: Session | None = None,
    caller: DBUser | None = None,
) -> ChrisMessageResponse:
    """Send a turn to Chris; persist only for verified authenticated callers."""
    message = form.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty."
        )

    existing_chat: Chat | None = None
    last_message_ms = 0
    if caller is not None:
        if db is None:
            raise RuntimeError("Database session is required for authenticated chat turns.")
        if form.chat_id:
            existing_chat = _get_owned_chat(db, form.chat_id, caller)
            stored_messages = _load_chat_messages(db, existing_chat.id)
            history_entries = _history_from_messages(stored_messages)
            if stored_messages:
                last_message_ms = max(m.created_at for m in stored_messages)
        else:
            history_entries = [
                {"role": m.role, "content": m.content} for m in form.history
            ]
    else:
        # Guest turns are strictly stateless: caller-supplied chat/user IDs are ignored.
        history_entries = [
            {"role": m.role, "content": m.content} for m in form.history
        ]

    try:
        reply = await send_message(message, bounded_history(history_entries))
    except ConfigError as exc:
        log.error("Chris configuration error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chris is temporarily unavailable. Please try again shortly.",
        ) from None
    except ChrisUnavailable:
        log.warning("Chris A2A call did not produce a completed answer.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chris is temporarily unavailable. Please try again shortly.",
        ) from None

    if hasattr(reply, "routing") and hasattr(reply, "text"):
        routing, text = reply.routing, reply.text
    else:
        routing, text = None, str(reply)
    selected = routing is not None and routing.status == "selected" and routing.agent
    if selected and routing and routing.agent:
        log.info("Selected expert: id=%s name=%s", routing.agent.id, routing.agent.name)

    chat_id: str | None = None
    if caller is not None:
        assert db is not None
        saved_chat = _persist_authenticated_turn(
            db=db,
            caller=caller,
            chat=existing_chat,
            message=message,
            reply_text=text,
            routing=routing,
            source_domain=form.source_domain,
            last_message_ms=last_message_ms,
        )
        chat_id = saved_chat.id

    return ChrisMessageResponse(
        response=text,
        chat_id=chat_id,
        routing=routing,
        routed_to=routing.agent.id if selected and routing and routing.agent else None,
        agent_name=routing.agent.name if selected and routing and routing.agent else None,
    )


def list_chats(db: Session, caller: DBUser) -> list[ChatSummary]:
    """List saved chats owned by ``caller``, pinned first then most recently updated."""
    chats = list(
        db.scalars(
            select(Chat)
            .where(Chat.user_id == caller.id, Chat.session_type == "authenticated")
            .order_by(
                Chat.is_pinned.desc(),
                Chat.updated_at.desc(),
                Chat.created_at.desc(),
                Chat.id.desc(),
            )
        )
    )
    return [_to_chat_summary(chat) for chat in chats]


def get_chat(db: Session, chat_id: str, caller: DBUser) -> ChatDetail:
    """Return one owned chat and its chronological messages."""
    chat = _get_owned_chat(db, chat_id, caller)
    messages = _load_chat_messages(db, chat.id)
    summary = _to_chat_summary(chat)
    return ChatDetail(
        **summary.model_dump(),
        messages=[_to_message_out(m) for m in messages],
    )


def update_chat(
    db: Session, chat_id: str, form: ChatUpdateForm, caller: DBUser
) -> ChatSummary:
    """Rename or pin/unpin an owned chat."""
    if form.title is None and form.is_pinned is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide title or is_pinned to update.",
        )
    chat = _get_owned_chat(db, chat_id, caller)
    if form.title is not None:
        chat.title = form.title
        chat.updated_at = int(time.time())
    if form.is_pinned is not None:
        chat.is_pinned = form.is_pinned
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        log.error("Failed to update chat (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not update conversation. Please try again shortly.",
        ) from None
    return _to_chat_summary(chat)


def delete_chat(db: Session, chat_id: str, caller: DBUser) -> None:
    """Delete an owned chat and cascade-delete its messages."""
    chat = _get_owned_chat(db, chat_id, caller)
    db.delete(chat)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        log.error("Failed to delete chat (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not delete conversation. Please try again shortly.",
        ) from None
