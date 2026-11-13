"""Stateless chat workflow: bound client history and ask Chris over A2A.

The database is used only to look up registered agent display details.
"""

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.chat.a2a_client import ChrisUnavailable, send_message
from app.chat.schemas import ChrisMessageForm, ChrisMessageResponse
from app.config import ConfigError
from app.history import bounded_history
from app.models import Agent as DBAgent
from app.registry.service import routable_agents

log = logging.getLogger(__name__)


async def handle_message(
    form: ChrisMessageForm,
    db: Session,
) -> ChrisMessageResponse:
    """Send a transient turn to Chris; never read or write stored conversations."""
    message = form.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty."
        )

    # Caller-supplied identity and chat IDs never authorize database access.
    history_entries = [
        {"role": m.role, "content": m.content} for m in form.history
    ]
    try:
        reply = await send_message(message, bounded_history(history_entries))

    except ConfigError as e:
        log.error("Chris configuration error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chris is temporarily unavailable. Please try again shortly.",
        )
    except ChrisUnavailable:
        log.warning("Chris A2A call did not produce a completed answer.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chris is temporarily unavailable. Please try again shortly.",
        )

    routing, text = reply.routing, reply.text
    if routing is not None and routing.status == "selected" and routing.agent:
        # Chris reports only the selected agent's id; the display name and description
        # come from this application's own agents table.
        try:
            record = db.get(DBAgent, routing.agent.id)
        except SQLAlchemyError:
            db.rollback()
            log.warning("Could not load selected expert display details.")
            record = None
        if record is not None:
            routing.agent.name = record.name
            routing.agent.description = record.description
            text = f"I found the {record.name} specialist for your question."
        else:
            text = "I found a specialist for your question."
        log.info("Selected expert: id=%s name=%s", routing.agent.id, routing.agent.name)
    selected = routing is not None and routing.status == "selected" and routing.agent
    return ChrisMessageResponse(
        response=text,
        chat_id=None,
        routing=routing,
        routed_to=routing.agent.id if selected else None,
        agent_name=routing.agent.name if selected else None,
    )


def list_active_agents(db: Session) -> list[dict[str, Any]]:
    """List active, reviewed agents for the frontend directory."""
    db_agents = routable_agents(db)
    return [
        {
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "endpoint_url": a.endpoint_url,
            "card_url": a.card_url,
            "trust_tier": a.trust_tier,
            "required_role": a.required_role,
            "skills": a.skills,
            "capabilities": a.capabilities,
            "is_featured": a.is_featured,
        }
        for a in db_agents
    ]
