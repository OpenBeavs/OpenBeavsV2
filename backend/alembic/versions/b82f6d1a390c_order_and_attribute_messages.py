"""Order messages per chat and reserve actual expert attribution.

Legacy timestamp ties are ordered deterministically by ID; their true historical
order and authors cannot be recovered. Keep timestamps in seconds; normalize
modern millisecond values written by the interim database branch. Downgrade does
not restore mixed timestamp units.
"""

import sqlalchemy as sa

from alembic import op

revision = "b82f6d1a390c"
down_revision = "a7c3e91d5b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("sequence", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("agent_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_messages_agent_id", "agents", ["agent_id"], ["id"], ondelete="SET NULL"
        )
    op.execute("""WITH ranked AS (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY chat_id ORDER BY
            CASE WHEN created_at >= 100000000000 THEN created_at ELSE created_at * 1000 END, id) AS position
        FROM messages
    ) UPDATE messages SET sequence = (SELECT position FROM ranked WHERE ranked.id = messages.id)""")
    # Contemporary epoch seconds have 10 digits, milliseconds have 13. This
    # repairs data written by the interim millisecond writer without altering
    # existing second-based timestamps. Sequence preserves subsecond ordering.
    op.execute(
        "UPDATE messages SET created_at = CAST(created_at / 1000 AS BIGINT) WHERE created_at >= 100000000000"
    )
    with op.batch_alter_table("messages") as batch:
        batch.alter_column("sequence", existing_type=sa.BigInteger(), nullable=False)
        batch.create_unique_constraint(
            "uq_messages_chat_sequence", ["chat_id", "sequence"]
        )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_constraint("uq_messages_chat_sequence", type_="unique")
        batch.drop_constraint("fk_messages_agent_id", type_="foreignkey")
        batch.drop_column("agent_id")
        batch.drop_column("sequence")
