"""Declarative bases for SQLAlchemy models, one per owner of data.

The chat system and the agent registry each own their tables. Each has its own base,
and so its own ``MetaData``, so that a foreign key or relationship from one owner's
table to the other's cannot be declared: SQLAlchemy resolves both within a single
``MetaData``. Either set of tables can therefore be created in a database that does
not hold the other.
"""

from sqlalchemy.orm import DeclarativeBase


class ChatSystemBase(DeclarativeBase):
    """Base class for the chat system's models: users, chats, messages, tickets."""


class RegistryBase(DeclarativeBase):
    """Base class for the agent registry's models: agents."""
