"""Stateless chat workflow: bound client history and ask Chris over A2A.

No database is read or written here. The selected expert's display name and
description arrive in Chris's routing result, which carries the registry's reply.
"""

import logging

from fastapi import HTTPException, status

from app.chat.a2a_client import ChrisUnavailable, send_message
from app.chat.schemas import ChrisMessageForm, ChrisMessageResponse
from app.config import ConfigError
from app.history import bounded_history
from app.models import User as DBUser

log = logging.getLogger(__name__)


async def handle_message(
    form: ChrisMessageForm,
    caller: DBUser | None = None,
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

    if hasattr(reply, "routing") and hasattr(reply, "text"):
        routing, text = reply.routing, reply.text
    else:
        routing, text = None, str(reply)
    if routing is not None and routing.status == "selected" and routing.agent:
        log.info("Selected expert: id=%s name=%s", routing.agent.id, routing.agent.name)
    selected = routing is not None and routing.status == "selected" and routing.agent
    return ChrisMessageResponse(
        response=text,
        chat_id=None,
        routing=routing,
        routed_to=routing.agent.id if selected else None,
        agent_name=routing.agent.name if selected else None,
    )

