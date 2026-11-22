"""Alembic environment for the Chat System's migrations.

The database is ``DATABASE_URL`` (local SQLite by default). Under PostgreSQL, connect
as the ``chat_system`` login: its ``search_path`` puts the tables, and Alembic's own
``alembic_version`` table, in the ``chat_system`` schema.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import application_services.models  # noqa: F401 (registers the tables with the metadata)
from application_services.config import get_database_url
from application_services.database.base import ChatSystemBase

config = context.config
config.set_main_option("sqlalchemy.url", get_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = ChatSystemBase.metadata


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
