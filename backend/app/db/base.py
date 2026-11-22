"""Declarative base for the chat system's SQLAlchemy models.

The chat system and the agent registry each own their tables. The registry's base,
``RegistryBase``, lives in its own package (``agent_registry.db.base``). Each base has
its own ``MetaData``, so that a foreign key or relationship from one owner's table to
the other's cannot be declared: SQLAlchemy resolves both within a single ``MetaData``.
Either set of tables can therefore be created in a database that does not hold the
other.
"""

from sqlalchemy.orm import DeclarativeBase


class ChatSystemBase(DeclarativeBase):
    """Base class for the chat system's models: users, chats, messages, tickets."""
