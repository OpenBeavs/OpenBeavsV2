"""add is_pinned to chats

Revision ID: 8c4e1b9a2f10
Revises: 34fddc6e996d
Create Date: 2026-11-25 13:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c4e1b9a2f10"
down_revision: str | None = "34fddc6e996d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``is_pinned`` to ``chats`` with false as the server default for existing rows."""
    op.add_column(
        "chats",
        sa.Column(
            "is_pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Remove ``is_pinned`` from ``chats``."""
    with op.batch_alter_table("chats") as batch_op:
        batch_op.drop_column("is_pinned")
