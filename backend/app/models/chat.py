"""Chat session database model.

Represents a multi-turn conversation initiated via the hub UI or embedded iframe.
"""

import time
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.message import Message
    from app.models.user import User


class Chat(Base):
    """Conversation session linking a user or guest to an agent."""

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
        doc="SHA-256 digest of the server-issued guest continuation token",
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Currently routed agent ID (NULL if orchestrator answers directly)",
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
    agent: Mapped["Agent | None"] = relationship(
        "Agent",
        back_populates="chats",
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="chat",
        cascade="all, delete-orphan",
        order_by="Message.sequence",
    )
