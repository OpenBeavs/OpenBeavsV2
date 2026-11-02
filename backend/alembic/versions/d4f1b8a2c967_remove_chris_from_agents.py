"""remove chris from agents

Chris is the orchestrator, not a registered agent: his discovery card is served by
code and he is never offered to the router. The early seed data nevertheless
inserted a ``chris`` row into ``agents``. This deletes it.

``chats.agent_id`` references ``agents.id`` with ON DELETE SET NULL, so no chat or
message is deleted. The reference is cleared explicitly first because SQLite does
not enforce foreign keys unless asked to.

Only the row with id ``chris`` is touched. The downgrade restores the row that
used to be seeded (and does nothing if a ``chris`` row already exists).

Revision ID: d4f1b8a2c967
Revises: a7c3e91d5b02
Create Date: 2026-10-30 12:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f1b8a2c967"
down_revision: str | None = "a7c3e91d5b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHRIS_ID = "chris"

agents = sa.table(
    "agents",
    sa.column("id", sa.String),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("endpoint_url", sa.Text),
    sa.column("card_url", sa.Text),
    sa.column("trust_tier", sa.String),
    sa.column("skills", sa.Text),
    sa.column("capabilities", sa.Text),
    sa.column("is_active", sa.Boolean),
    sa.column("is_featured", sa.Boolean),
    sa.column("status", sa.String),
    sa.column("created_at", sa.BigInteger),
    sa.column("updated_at", sa.BigInteger),
)
chats = sa.table("chats", sa.column("agent_id", sa.String))

# The row the original seed inserted, restored by the downgrade.
CHRIS_ROW = {
    "id": CHRIS_ID,
    "name": "Chris",
    "description": (
        "OpenBeavs orchestrator. Routes your queries to installed agents and "
        "answers directly when no agent matches."
    ),
    "endpoint_url": "/chris/message",
    "card_url": "/chris/.well-known/agent.json",
    "trust_tier": "public",
    "skills": [
        {
            "id": "route",
            "name": "Route Query",
            "description": (
                "Classify a user query and delegate to the best installed agent."
            ),
            "tags": ["orchestration", "routing"],
        }
    ],
    "capabilities": {"streaming": True},
    "is_active": True,
    "is_featured": True,
    "status": "approved",
    "created_at": 1778023031,
    "updated_at": 1778023031,
}


def upgrade() -> None:
    """Detach Chris from any chat, then delete his row (no-op if it is absent)."""
    op.execute(chats.update().where(chats.c.agent_id == CHRIS_ID).values(agent_id=None))
    op.execute(agents.delete().where(agents.c.id == CHRIS_ID))


def downgrade() -> None:
    """Restore the seeded Chris row, leaving an existing one untouched.

    Only the seeded row comes back: the chats that referenced Chris were detached
    by the upgrade and any edits made to his row meanwhile are lost.
    """
    dialect = op.get_context().dialect.name
    # The JSON columns are written as JSON text: SQLAlchemy cannot render a JSON
    # value as a literal in offline (--sql) mode, and the text form is identical
    # to what the ORM stores.
    skills = json.dumps(CHRIS_ROW["skills"])
    capabilities = json.dumps(CHRIS_ROW["capabilities"])
    if dialect == "postgresql":
        values = {
            **CHRIS_ROW,
            "skills": sa.cast(sa.literal(skills, sa.Text), postgresql.JSON),
            "capabilities": sa.cast(sa.literal(capabilities, sa.Text), postgresql.JSON),
        }
        statement = postgresql.insert(agents).values(values)
    elif dialect == "sqlite":
        values = {**CHRIS_ROW, "skills": skills, "capabilities": capabilities}
        statement = sqlite.insert(agents).values(values)
    else:
        raise NotImplementedError(f"Unsupported database dialect: {dialect}")
    op.execute(statement.on_conflict_do_nothing(index_elements=["id"]))
