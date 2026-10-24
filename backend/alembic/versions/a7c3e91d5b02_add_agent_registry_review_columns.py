"""add agent registry review columns

Adds the review workflow to the unified ``agents`` table: a ``status`` that gates
routing, who submitted and who reviewed an agent, and a unique constraint on
``card_url`` so one card is registered once.

Existing rows (the seeded production agents and anything already in Cloud SQL)
are backfilled to ``approved`` so they keep routing exactly as before. The
column default is then removed, so every new row must set its status explicitly.

Revision ID: a7c3e91d5b02
Revises: 5f055aea1c94
Create Date: 2026-10-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e91d5b02"
down_revision: str | None = "5f055aea1c94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add review columns (existing rows become 'approved') and a unique card URL."""
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="approved",
            )
        )
        batch_op.add_column(
            sa.Column("submitted_by", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reviewed_by", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(sa.Column("reviewed_at", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("review_note", sa.Text(), nullable=True))
        batch_op.create_unique_constraint("uq_agents_card_url", ["card_url"])

    # The default only existed to backfill existing rows. Drop it so a new row
    # can never become routable by forgetting to set a status.
    with op.batch_alter_table("agents") as batch_op:
        batch_op.alter_column("status", server_default=None)


def downgrade() -> None:
    """Remove the review columns and the unique card URL."""
    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_constraint("uq_agents_card_url", type_="unique")
        batch_op.drop_column("review_note")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("reviewed_by")
        batch_op.drop_column("submitted_by")
        batch_op.drop_column("status")
