"""Alembic environment for the Agent Registry's migrations.

The database is ``DATABASE_URL`` (local SQLite by default). Under PostgreSQL, connect
as the ``registry`` login: its ``search_path`` puts the tables, and Alembic's own
``alembic_version`` table, in the ``registry`` schema.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import agent_registry.models  # noqa: F401 (registers the tables with the metadata)
from agent_registry.config import get_database_url
from agent_registry.database.base import RegistryBase

config = context.config
config.set_main_option("sqlalchemy.url", get_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = RegistryBase.metadata


def run_migrations_offline() -> None:
    """Emit the SQL without connecting (``alembic upgrade --sql``)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply the migrations."""
    url = get_database_url()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
