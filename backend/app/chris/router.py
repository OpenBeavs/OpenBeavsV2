"""Chris HTTP routes.

POST /chris/message: send a message to Chris and get Gemini's answer back.
Kept thin; model access lives in ``llm.py``.
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.chris.llm import CHRIS_SYSTEM_PROMPT, LLMError, generate
from app.config import ConfigError

log = logging.getLogger(__name__)

router = APIRouter()


class HistoryMessage(BaseModel):
    """One earlier turn in the conversation."""

    role: Literal["user", "assistant"]
    content: str


class ChrisMessageForm(BaseModel):
    """Request body for POST /chris/message."""

    message: str
    history: list[HistoryMessage] = []


class ChrisMessageResponse(BaseModel):
    """Response body: Chris's reply."""

    response: str


@router.post("/message", response_model=ChrisMessageResponse)
async def chris_message(form: ChrisMessageForm) -> ChrisMessageResponse:
    """Answer a user message directly via the configured model.

    Raises:
        HTTPException: 400 for an empty message, 500 if the server is missing
            configuration, 503 if the model call fails.
    """
    message = form.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty."
        )

    messages = [
        {"role": "system", "content": CHRIS_SYSTEM_PROMPT},
        *({"role": m.role, "content": m.content} for m in form.history),
        {"role": "user", "content": message},
    ]

    try:
        reply = await generate(messages)
    except ConfigError as e:
        log.error("Chris configuration error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
    except LLMError as e:
        log.error("Chris model call failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chris is temporarily unavailable. Please try again shortly.",
        )

    return ChrisMessageResponse(response=reply)
