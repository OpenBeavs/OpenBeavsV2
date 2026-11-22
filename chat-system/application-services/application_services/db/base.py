"""Declarative base for the chat system's SQLAlchemy models.

The chat system and the agent registry each own their tables, each in a database (or,
under PostgreSQL, a schema) of its own. The registry's models live in its own package,
which this one never imports. This base has its own ``MetaData`` holding the chat
system's tables alone, so a foreign key or relationship into the registry's table
cannot be declared here: SQLAlchemy resolves both within a single ``MetaData``.
"""

from sqlalchemy.orm import DeclarativeBase


class ChatSystemBase(DeclarativeBase):
    """Base class for the chat system's models: users, chats, messages, tickets."""
