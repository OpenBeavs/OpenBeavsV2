# Migrations: chat_system schema

Alembic migrations for the Chat System's tables, and only those. A table that refers to an agent stores the agent's ID as plain text, with no foreign key, because the agent catalog belongs to the Registry.
