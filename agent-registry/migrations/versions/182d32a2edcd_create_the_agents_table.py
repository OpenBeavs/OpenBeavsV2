"""create the agents table

The Agent Registry's first migration. It creates the ``agents`` table exactly as the
registry's earlier migrations, run in the chat backend's history up to its revision
``e6b2c4a9f815``, left it: the same columns in the same order, no default on
``status`` (so a new row must choose its review status), and one registration per
card URL. It creates no other table.

A database those earlier migrations already brought to ``e6b2c4a9f815`` holds this
table already. Record this revision there with ``alembic stamp --purge 182d32a2edcd``
instead of running it (see the registry's README, "Database").

Revision ID: 182d32a2edcd
Revises:
Create Date: 2026-11-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "182d32a2edcd"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``agents`` with its review columns and its unique card URL."""
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("endpoint_url", sa.String(length=512), nullable=False),
        sa.Column("card_url", sa.String(length=512), nullable=True),
        sa.Column("trust_tier", sa.String(length=32), nullable=False),
        sa.Column("required_role", sa.String(length=64), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_featured", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("submitted_by", sa.String(length=255), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.BigInteger(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_url", name="uq_agents_card_url"),
    )


def downgrade() -> None:
    """Drop the table, and every registered agent with it."""
    op.drop_table("agents")
