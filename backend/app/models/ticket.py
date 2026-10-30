"""Ticket and user feedback database model."""

import time
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Ticket(Base):
    """User-submitted feedback, issue report, or support request."""

    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Unique UUID identifier for the ticket",
    )
    user_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Submitting user ONID / ID (NULL for anonymous feedback)",
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="Submitter contact name",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Submitter contact email",
    )
    issue_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Issue category: 'bug', 'feature_request', or 'general_feedback'",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Detailed explanation of the issue or feedback",
    )
    info: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Client telemetry (browser, OS, referring URL)",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="new",
        doc="Lifecycle state: 'new', 'in_progress', 'resolved', 'closed'",
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        doc="Submission timestamp in epoch seconds",
    )
    resolved_at: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        doc="Resolution timestamp in epoch seconds (NULL if unresolved)",
    )

    # Relationships
    user: Mapped["User | None"] = relationship(
        "User",
        back_populates="tickets",
    )
