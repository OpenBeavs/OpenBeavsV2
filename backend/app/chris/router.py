"""Chris HTTP routes.

POST /chris/message: route a message to an agent, or answer it directly.
Kept thin; model access lives in ``llm.py`` and routing in ``agent_selection.py``.
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.chris.agent_selection import choose_agent
from app.chris.agents import MOCK_AGENTS, Agent
from app.chris.llm import LLMError, generate
from app.chris.prompts import build_direct_prompt
from app.config import ConfigError, env_flag

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
    """Response body.

    ``routed_to`` and ``agent_name`` are set when Chris picked an agent. The
    ``routing_*`` fields show the model's decision (when routing ran), which
    helps tune routing even when the answer came directly from Chris.
    """

    response: str
    routed_to: str | None = None
    agent_name: str | None = None
    routing_confidence: float | None = None
    routing_reason: str | None = None


def _installed_agents() -> list[Agent]:
    """Return the agents Chris can route to.

    v2 has no agents database yet, so this is empty unless
    CHRIS_USE_MOCK_AGENTS is set, which returns the mock list for testing.
    """
    return MOCK_AGENTS if env_flag("CHRIS_USE_MOCK_AGENTS") else []


@router.post("/message", response_model=ChrisMessageResponse)
async def chris_message(form: ChrisMessageForm) -> ChrisMessageResponse:
    """Route a message to an agent or answer it directly via the configured model.

    Agent calling is not implemented yet: when an agent is chosen, the reply
    says so instead of calling it.

    Raises:
        HTTPException: 400 for an empty message, 500 if the server is missing
            configuration, 503 if the model call fails.
    """
    message = form.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty."
        )

    agents = _installed_agents()

    try:
        selection = await choose_agent(message, agents)

        if selection.agent:
            return ChrisMessageResponse(
                response=(
                    f"Chris would route this to {selection.agent.name}. "
                    "Calling agents is not implemented yet."
                ),
                routed_to=selection.agent.id,
                agent_name=selection.agent.name,
                routing_confidence=selection.confidence,
                routing_reason=selection.reason,
            )

        messages = [
            {"role": "system", "content": build_direct_prompt(agents)},
            *({"role": m.role, "content": m.content} for m in form.history),
            {"role": "user", "content": message},
        ]
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

    return ChrisMessageResponse(
        response=reply,
        routing_confidence=selection.confidence,
        routing_reason=selection.reason,
    )
