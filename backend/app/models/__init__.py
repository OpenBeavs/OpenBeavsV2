"""Models package initialization.

Exports all declarative models so Alembic and FastAPI can import them centrally.
``Agent`` belongs to the agent registry (``RegistryBase``); the others belong to the
chat system (``ChatSystemBase``). See ``app.db.base``.
"""

from app.models.agent import Agent
from app.models.chat import Chat
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.user import User

__all__ = ["Agent", "Chat", "Message", "Ticket", "User"]
