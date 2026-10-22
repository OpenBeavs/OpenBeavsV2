"""Message turn database model.

Represents an individual conversational turn in a chat session.
"""

import time
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, BigInteger, ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chat import Chat


class Message(Base):
    """An individual message turn within a chat conversation."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique UUID identifier for the message",
    )
    chat_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="References parent chat session (cascades on delete)",
    )
    sender_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Originator type: 'user', 'agent', or 'system'",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Turn text content (or base64 ciphertext if envelope encrypted)",
    )
    encrypted_dek: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        doc="Per-chat Data Encryption Key wrapped by user KMS key (NULL if unencrypted)",
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Non-sensitive metadata (routing latency_ms, tokens, error_code)",
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        index=True,
        doc="Message timestamp in epoch seconds",
    )

    # Relationships
    chat: Mapped["Chat"] = relationship(
        "Chat",
        back_populates="messages",
    )
