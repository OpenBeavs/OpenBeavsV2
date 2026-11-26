"""Frontend chat HTTP routes, separate from Chris's A2A protocol endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from application_services.auth.dependencies import get_current_user, get_optional_user
from application_services.chat import service
from application_services.chat.schemas import (
    ChatDetail,
    ChatSummary,
    ChatUpdateForm,
    ChrisMessageForm,
    ChrisMessageResponse,
)
from application_services.database.session import get_db
from application_services.models import User as DBUser

router = APIRouter()


@router.post("/message", response_model=ChrisMessageResponse)
async def chris_message(
    form: ChrisMessageForm,
    db: Annotated[Session, Depends(get_db)],
    caller: Annotated[DBUser | None, Depends(get_optional_user)] = None,
) -> ChrisMessageResponse:
    """Handle a chat turn; persist only when called with a verified session."""
    return await service.handle_message(form, db=db, caller=caller)


@router.get("/chats", response_model=list[ChatSummary])
def list_chats(
    caller: Annotated[DBUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ChatSummary]:
    """List saved chats belonging to the signed-in user."""
    return service.list_chats(db, caller)


@router.get("/chats/{chat_id}", response_model=ChatDetail)
def get_chat(
    chat_id: str,
    caller: Annotated[DBUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatDetail:
    """Return one saved chat and its turns for the signed-in owner."""
    return service.get_chat(db, chat_id, caller)


@router.patch("/chats/{chat_id}", response_model=ChatSummary)
def update_chat(
    chat_id: str,
    form: ChatUpdateForm,
    caller: Annotated[DBUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatSummary:
    """Rename or pin/unpin a saved chat owned by the signed-in user."""
    return service.update_chat(db, chat_id, form, caller)


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(
    chat_id: str,
    caller: Annotated[DBUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Delete a saved chat owned by the signed-in user."""
    service.delete_chat(db, chat_id, caller)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
