"""drop the foreign key from chats to agents

``chats.agent_id`` used to reference ``agents.id``. The agents table belongs to the
agent registry and the chats table to the chat system, and the two are to sit behind
separate database logins, where a constraint from one into the other cannot exist. The
column stays, with its index and its values, as a plain string holding the id the
registry gave the agent.

PostgreSQL drops the constraint in place. SQLite cannot drop a constraint, so the table
is rebuilt (Alembic batch mode). With SQLite foreign-key enforcement switched on, the
rebuild's ``DROP TABLE chats`` would cascade and delete every message, and SQLite
ignores an attempt to switch enforcement off inside a transaction, so the upgrade
refuses to run in that state. The application never switches enforcement on. The
rebuild also writes the remaining constraint, to ``users``, under its convention name.

The downgrade restores the constraint (ON DELETE SET NULL). It first clears any
``agent_id`` that no longer names a row in ``agents``, because the constraint could
not be created over such values.

Revision ID: e6b2c4a9f815
Revises: d4f1b8a2c967
Create Date: 2026-11-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "e6b2c4a9f815"
down_revision: str | None = "d4f1b8a2c967"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The name PostgreSQL gives the constraint the first migration created unnamed.
POSTGRES_NAME = "chats_agent_id_fkey"
# SQLite keeps the constraint unnamed. Batch mode finds it through this convention.
SQLITE_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
SQLITE_NAME = "fk_chats_agent_id_agents"

chats = sa.table("chats", sa.column("agent_id", sa.String))
agents = sa.table("agents", sa.column("id", sa.String))


def _refuse_sqlite_foreign_key_enforcement() -> None:
    """Stop before a table rebuild that would cascade into ``messages``."""
    if context.is_offline_mode():
        return
    if op.get_bind().exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError(
            "SQLite foreign-key enforcement is on. Rebuilding the chats table with it "
            "on deletes every message (ON DELETE CASCADE). Run this migration on a "
            "connection that has not issued PRAGMA foreign_keys=ON."
        )


def upgrade() -> None:
    """Remove the constraint; keep the column, its index and its values."""
    dialect = op.get_context().dialect.name
    if dialect == "sqlite":
        _refuse_sqlite_foreign_key_enforcement()
        with op.batch_alter_table("chats", naming_convention=SQLITE_NAMING) as batch_op:
            batch_op.drop_constraint(SQLITE_NAME, type_="foreignkey")
    elif context.is_offline_mode():
        # No connection to inspect: address the constraint by its default name.
        op.execute(f"ALTER TABLE chats DROP CONSTRAINT IF EXISTS {POSTGRES_NAME}")
    else:
        # Drop it under whatever name this database gave it.
        for key in sa.inspect(op.get_bind()).get_foreign_keys("chats"):
            if (
                key["referred_table"] == "agents"
                and key["constrained_columns"] == ["agent_id"]
            ):
                op.drop_constraint(key["name"], "chats", type_="foreignkey")


def downgrade() -> None:
    """Restore the constraint, detaching chats whose agent no longer exists."""
    op.execute(
        chats.update()
        .where(chats.c.agent_id.is_not(None))
        .where(chats.c.agent_id.not_in(sa.select(agents.c.id)))
        .values(agent_id=None)
    )
    if op.get_context().dialect.name == "sqlite":
        _refuse_sqlite_foreign_key_enforcement()
        with op.batch_alter_table("chats", naming_convention=SQLITE_NAMING) as batch_op:
            batch_op.create_foreign_key(
                SQLITE_NAME, "agents", ["agent_id"], ["id"], ondelete="SET NULL"
            )
    else:
        op.create_foreign_key(
            POSTGRES_NAME, "chats", "agents", ["agent_id"], ["id"], ondelete="SET NULL"
        )
