"""Frontend chat HTTP routes, separate from Chris's A2A protocol endpoint."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.chat import service
from app.chat.schemas import AgentSummary, ChrisMessageForm, ChrisMessageResponse
from app.db import get_db

router = APIRouter()


@router.post("/message", response_model=ChrisMessageResponse)
async def chris_message(
    form: ChrisMessageForm,
    db: Annotated[Session, Depends(get_db)],
) -> ChrisMessageResponse:
    """Handle a chat turn using the existing Chris response contract."""
    return await service.handle_message(form, db)


@router.get("/agents", response_model=list[AgentSummary])
def list_active_agents(db: Annotated[Session, Depends(get_db)]) -> list[dict[str, Any]]:
    """List the active, reviewed agents available to chat."""
    return service.list_active_agents(db)

