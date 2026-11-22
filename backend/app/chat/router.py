"""Frontend chat HTTP routes, separate from Chris's A2A protocol endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_optional_user
from app.chat import service
from app.chat.schemas import ChrisMessageForm, ChrisMessageResponse
from app.models import User as DBUser

router = APIRouter()


@router.post("/message", response_model=ChrisMessageResponse)
async def chris_message(
    form: ChrisMessageForm,
    caller: Annotated[DBUser | None, Depends(get_optional_user)] = None,
) -> ChrisMessageResponse:
    """Handle a chat turn using the existing Chris response contract."""
    if caller is not None:
        try:
            return await service.handle_message(form, caller=caller)
        except TypeError:
            return await service.handle_message(form)
    return await service.handle_message(form)
