"""Script to initialize all tables in the configured database via Alembic.

Works against local SQLite or Google Cloud SQL PostgreSQL depending
on the DATABASE_URL environment variable.
"""

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.db.seed_agents import seed_agents
from app.db.session import engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def init_tables() -> None:
    """Apply Alembic migrations up to head to create and version all tables."""
    log.info("Connecting to target database: %s", engine.url)
    backend_dir = Path(__file__).resolve().parents[2]
    alembic_ini_path = backend_dir / "alembic.ini"
    log.info("Applying Alembic migrations using config: %s", alembic_ini_path)

    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(alembic_cfg, "head")
    log.info("Alembic upgrade head completed successfully.")


def init_and_seed() -> None:
    """Create all tables via Alembic and seed initial production agents."""
    init_tables()
    seed_agents()


if __name__ == "__main__":
    init_and_seed()
