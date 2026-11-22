"""Declarative base for the Agent Registry's models.

The registry owns its tables and keeps them in its own ``MetaData``, so no model here
can declare a foreign key or relationship into another system's tables: SQLAlchemy
resolves both within a single ``MetaData``. The registry's tables can therefore be
created in a database that holds nothing else.
"""

from sqlalchemy.orm import DeclarativeBase


class RegistryBase(DeclarativeBase):
    """Base class for the agent registry's models: agents."""
