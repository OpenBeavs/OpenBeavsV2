"""Script to initialize all tables in the configured database.

Works against local SQLite or Google Cloud SQL PostgreSQL depending
on the DATABASE_URL environment variable.
"""

import logging

from app.db.base import Base
from app.db.seed_agents import seed_agents
from app.db.session import engine
from app.models import Agent, Chat, Message, Ticket, User  # noqa: F401

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def init_tables() -> None:
    """Create all 5 database tables using Base.metadata."""
    log.info("Connecting to target database: %s", engine.url)
    Base.metadata.create_all(bind=engine)
    log.info(
        "All 5 tables created successfully: agents, users, chats, messages, tickets."
    )


def init_and_seed() -> None:
    """Create all tables and seed initial production agents."""
    init_tables()
    seed_agents()


if __name__ == "__main__":
    init_and_seed()
