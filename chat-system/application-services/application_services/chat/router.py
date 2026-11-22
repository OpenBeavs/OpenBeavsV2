"""Frontend chat HTTP routes, separate from Chris's A2A protocol endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from application_services.auth.dependencies import get_optional_user
from application_services.chat import service
from application_services.chat.schemas import ChrisMessageForm, ChrisMessageResponse
from application_services.models import User as DBUser

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
