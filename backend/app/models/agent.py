"""Agent database model.

Represents an A2A (Agent-to-Agent) service registered with the hub.
"""

import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, BigInteger, Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chat import Chat


class Agent(Base):
    """Registered A2A agent metadata and routing configuration."""

    __tablename__ = "agents"
    # One registry entry per card URL. NULL card URLs are allowed (and do not clash).
    __table_args__ = (UniqueConstraint("card_url", name="uq_agents_card_url"),)

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        doc="Unique slug identifier (e.g. 'honors-college') or UUID",
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="Human-readable agent display name",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Agent purpose and scope",
    )
    endpoint_url: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        doc="A2A JSON-RPC URL for message/send",
    )
    card_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        doc="URL to hosted /.well-known/agent.json card",
    )
    trust_tier: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="public",
        doc="Access tier: 'public', 'authenticated', or 'privileged'",
    )
    required_role: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="Optional OSU role required (e.g. 'student', 'staff', 'faculty')",
    )
    skills: Mapped[list[Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=list,
        doc="List of skill tags, descriptions, and examples",
    )
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        doc="Supported modes (streaming, audio, multimodal)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        doc="Whether agent is available for routing",
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Whether agent is highlighted on the hub showcase",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        doc=(
            "Registry review status: 'pending' (submitted, not routable), "
            "'approved' or 'provisional' (routable), 'revoked' (not routable). "
            "New rows default to 'pending'; only an admin review changes it."
        ),
    )
    submitted_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Identity (email) of whoever submitted the agent; NULL for seeded agents",
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Identity (email) of the admin who last reviewed the agent",
    )
    reviewed_at: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        doc="Epoch seconds of the last admin review",
    )
    review_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Reviewer note, or an automatic flag raised when the card was submitted",
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        doc="Creation timestamp in epoch seconds",
    )
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
        doc="Last update timestamp in epoch seconds",
    )

    # Relationships
    chats: Mapped[list["Chat"]] = relationship(
        "Chat",
        back_populates="agent",
    )
