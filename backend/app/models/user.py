"""User database model.

Represents an authenticated OSU identity verified via Microsoft SSO (OIDC).
"""

import time
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chat import Chat
    from app.models.ticket import Ticket


class User(Base):
    """Authenticated user record originating from OSU SSO claims."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        doc="OSU ONID username or OIDC subject claim (sub)",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        doc="Official @oregonstate.edu email address",
    )
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="User full name from SSO profile claims",
    )
    role: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="student",
        doc="OSU role: 'student', 'staff', 'faculty', or 'admin'",
    )
    kms_key_ref: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="KMS resource path for envelope encryption key",
    )
    created_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        doc="Account provisioning timestamp in epoch seconds",
    )
    last_login_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        doc="Last active login timestamp in epoch seconds",
    )

    # Relationships
    chats: Mapped[list["Chat"]] = relationship(
        "Chat",
        back_populates="user",
    )
    tickets: Mapped[list["Ticket"]] = relationship(
        "Ticket",
        back_populates="user",
    )
