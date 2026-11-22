"""Chat session database model.

Represents a multi-turn conversation initiated via the hub UI or embedded iframe.
"""

import time
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ChatSystemBase

if TYPE_CHECKING:
    from app.models.message import Message
    from app.models.user import User


class Chat(ChatSystemBase):
    """Conversation session of a user or guest, with the agent it was last routed to."""

    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique UUID identifier for the chat session",
    )
    user_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="References authenticated user; NULL for guest / iframe sessions",
    )
    guest_session_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="Ephemeral session token for unauthenticated iframe guests",
    )
    # A plain value, not a foreign key: the agents table belongs to the agent
    # registry, which the chat tables must not reference.
    agent_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="Registry ID of the currently routed agent (NULL if orchestrator answers directly)",
    )
    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default="New Conversation",
        doc="User-visible or generated conversation title",
    )
    source_domain: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        doc="Originating OSU site where iframe was embedded (e.g. library.oregonstate.edu)",
    )
    session_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="guest",
        doc="Identity mode: 'authenticated', 'guest', or 'a2a'",
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        doc="Session creation timestamp in epoch seconds",
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
        doc="Last message activity timestamp in epoch seconds",
    )
    expires_at: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
        doc="TTL purge timestamp for guest iframe chats; NULL for authenticated users",
    )

    # Relationships
    user: Mapped["User | None"] = relationship(
        "User",
        back_populates="chats",
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="chat",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
