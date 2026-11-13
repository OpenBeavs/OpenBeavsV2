"""Frontend chat HTTP routes, separate from Chris's A2A protocol endpoint."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_user
from app.chat import service
from app.chat.schemas import AgentSummary, ChrisMessageForm, ChrisMessageResponse
from app.db import get_db
from app.models import User as DBUser

router = APIRouter()


@router.post("/message", response_model=ChrisMessageResponse)
async def chris_message(
    form: ChrisMessageForm,
    db: Annotated[Session, Depends(get_db)],
    caller: Annotated[DBUser | None, Depends(get_optional_user)] = None,
) -> ChrisMessageResponse:
    """Handle a chat turn using the existing Chris response contract."""
    if caller is not None:
        try:
            return await service.handle_message(form, db, caller=caller)
        except TypeError:
            return await service.handle_message(form, db)
    return await service.handle_message(form, db)


@router.get("/agents", response_model=list[AgentSummary])
def list_active_agents(db: Annotated[Session, Depends(get_db)]) -> list[dict[str, Any]]:
    """List the active, reviewed agents available to chat."""
    return service.list_active_agents(db)


@router.delete("/chats/expired")
def delete_expired_chats(db: Annotated[Session, Depends(get_db)]) -> dict[str, int]:
    """Purge expired guest chats using the existing maintenance endpoint."""
    return {"purged": service.purge_expired_chats(db)}
