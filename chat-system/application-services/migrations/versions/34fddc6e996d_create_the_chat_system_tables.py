"""create the chat system's tables

The Chat System's first migration. It creates ``users``, ``chats``, ``messages`` and
``tickets`` exactly as the chat backend's earlier migrations left them at their head,
revision ``e6b2c4a9f815``: the same columns in the same order, the same indexes, and
the same foreign keys. ``chats.agent_id`` is a plain indexed string with no foreign key,
because the agent catalog belongs to the Agent Registry. It creates no other table.

The earlier migrations rebuilt ``chats`` on SQLite and so named its foreign key to
``users`` there; PostgreSQL named it when it was created. This revision gives the
constraint those same names, so a database built here and one adopted from the
earlier history carry identical constraints.

A database those earlier migrations already brought to ``e6b2c4a9f815`` holds these
tables already. Record this revision there with ``alembic stamp --purge 34fddc6e996d``
instead of running it (see the README, "Database").

Revision ID: 34fddc6e996d
Revises:
Create Date: 2026-11-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "34fddc6e996d"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The name each dialect's earlier history left on the chats-to-users foreign key.
CHATS_USER_FK = {"sqlite": "fk_chats_user_id_users", "postgresql": "chats_user_id_fkey"}


def upgrade() -> None:
    """Create the four tables, their indexes, and their foreign keys."""
    dialect = op.get_context().dialect.name
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("kms_key_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("last_login_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "chats",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("guest_session_id", sa.String(length=64), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("source_domain", sa.String(length=255), nullable=True),
        sa.Column("session_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=CHATS_USER_FK.get(dialect),
            ondelete="SET NULL",
        ),
    )
    for column in ("agent_id", "expires_at", "guest_session_id", "source_domain", "user_id"):
        op.create_index(op.f(f"ix_chats_{column}"), "chats", [column], unique=False)

    op.create_table(
        "tickets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("issue_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("info", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("resolved_at", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chat_id", sa.String(length=36), nullable=False),
        sa.Column("sender_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("encrypted_dek", sa.LargeBinary(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_chat_id"), "messages", ["chat_id"], unique=False)
    op.create_index(
        op.f("ix_messages_created_at"), "messages", ["created_at"], unique=False
    )


def downgrade() -> None:
    """Drop the four tables, and every user, chat, message and ticket with them."""
    op.drop_index(op.f("ix_messages_created_at"), table_name="messages")
    op.drop_index(op.f("ix_messages_chat_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_table("tickets")
    for column in ("user_id", "source_domain", "guest_session_id", "expires_at", "agent_id"):
        op.drop_index(op.f(f"ix_chats_{column}"), table_name="chats")
    op.drop_table("chats")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
