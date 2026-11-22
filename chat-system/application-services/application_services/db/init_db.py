"""Create or update the chat system's tables in the configured database via Alembic.

Works against local SQLite or Google Cloud SQL PostgreSQL depending on the
DATABASE_URL environment variable. Run from this package's folder:
``python -m application_services.db.init_db``. It creates the chat system's tables
only; the Agent Registry seeds its own agents (``python -m agent_registry.db.seed_agents``
from ``agent-registry/``).
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from application_services.db.session import engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# The folder holding alembic.ini and migrations/: two levels above this file.
PACKAGE_DIR = Path(__file__).resolve().parents[2]


def init_tables() -> None:
    """Apply the chat system's Alembic migrations up to head."""
    log.info("Connecting to target database: %s", engine.url)
    alembic_ini_path = PACKAGE_DIR / "alembic.ini"
    log.info("Applying Alembic migrations using config: %s", alembic_ini_path)

    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("script_location", str(PACKAGE_DIR / "migrations"))
    command.upgrade(alembic_cfg, "head")
    log.info("Alembic upgrade head completed successfully.")


if __name__ == "__main__":
    init_tables()
