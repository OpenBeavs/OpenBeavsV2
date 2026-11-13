"""Registry A2A selection adapter (official SDK, protocol 1.0).

Accepts a question and optional data-part history; metadata history is a fallback
only when no data-part list exists. Replies with one text part containing exactly
{"agent": {"id", "endpoint_url"}} or {"agent": "none"}. Failures are JSON-RPC
errors carrying an allow-listed code (RETRYABLE), never internal details.

The executor reads eligible agents, asks the selector, and rechecks the chosen row
before replying. It neither answers the question nor calls the expert. See
docs/registry.md for protocol details, limits and authentication.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from a2a.helpers import (
    get_data_parts,
    get_message_text,
    new_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    SecurityRequirement,
    SecurityScheme,
)
from a2a.utils.errors import (
    A2AError,
    InternalError,
    InvalidParamsError,
    UnsupportedOperationError,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Agent
from app.registry import selection
from app.registry.cards import clean_text
from app.registry.llm import LLMCall, ModelLimiter
from app.registry.selection import Candidate, SelectionResult, Turn
from app.registry.service import get_routable_agent, routable_agents

log = logging.getLogger(__name__)

# Whether trying again may help, per error code. The code is the only thing on the wire.
RETRYABLE: dict[str, bool] = {
    "invalid_request": False,
    "not_configured": False,
    "selection_unavailable": True,
    "selection_busy": True,
    "invalid_model_reply": True,
    "agent_unavailable": True,
    "registry_capacity_exceeded": False,
    "registry_unavailable": True,
    "internal_error": True,
}
SKILL_ID = "select_agent"
# The registry agent's own software version. It is NOT the A2A protocol version,
# which is advertised in the card's supported interface.
AGENT_VERSION = "0.1.0"
A2A_PROTOCOL_VERSION = "1.0"
MOUNT_PATH = "/a2a/registry"

SessionFactory = Callable[[], Session]


def build_agent_card(base_url: str) -> AgentCard:
    """The registry's Agent Card. ``base_url`` is the public origin, no trailing slash."""
    return AgentCard(
        name="OpenBeavs Agent Registry",
        description=(
            "Selects the best registered OpenBeavs expert agent for a user's question "
            "and returns that expert's A2A endpoint. It does not answer questions and "
            "does not call the expert."
        ),
        version=AGENT_VERSION,
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}{MOUNT_PATH}/",
                protocol_binding="JSONRPC",
                protocol_version=A2A_PROTOCOL_VERSION,
            )
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["application/json", "text/plain"],
        skills=[
            AgentSkill(
                id=SKILL_ID,
                name="Select expert agent",
                description=(
                    "Given a user question (and optionally a few earlier turns), "
                    "returns the best eligible expert agent, no match, or an error. "
                    'Reply: one text part with JSON, {"agent": {"id", "endpoint_url"}} or '
                    '{"agent": "none"}; a failure is an A2A error whose message is a code.'
                ),
                tags=["registry", "routing", "selection"],
                examples=["Which expert can tell me about OSU admissions?"],
            )
        ],
        security_schemes={
            "google_id_token": SecurityScheme(
                http_auth_security_scheme={
                    "scheme": "bearer",
                    "bearer_format": "JWT",
                    "description": "A Google-issued ID token for an allowed service account.",
                }
            )
        },
        security_requirements=[SecurityRequirement(schemes={"google_id_token": {}})],
    )


def wire_text(result: SelectionResult) -> str:
    """The reply text: exactly the JSON Chris reads (see the module docstring).

    Raises:
        ValueError: If ``result`` is an error (those are raised as A2A errors, not sent).
    """
    if result.status == selection.SELECTED and result.agent is not None:
        agent: Any = {
            "id": result.agent.id,
            "endpoint_url": result.agent.endpoint_url,
        }
    elif result.status == selection.NO_MATCH:
        agent = "none"
    else:
        raise ValueError("Only a selection or a no-match can be sent as a reply.")
    return json.dumps({"agent": agent}, separators=(",", ":"))


def error_for(result: SelectionResult) -> A2AError:
    """The A2A error for a failed selection. Its message is the code and nothing else."""
    code = result.error_code or "internal_error"
    if code == "invalid_request":
        return InvalidParamsError(code)
    return InternalError(code)


def _turns(raw: Any) -> list[Turn]:
    """Clean a raw history list into turns; anything malformed is skipped."""
    turns: list[Turn] = []
    if not isinstance(raw, list):
        return turns
    for item in raw:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            text = clean_text(content)[: selection.MAX_HISTORY_CHARS]
            if text:
                turns.append(Turn(role=role, content=text))
    return turns


def parse_request(
    message: Any, request_metadata: dict[str, Any] | None = None
) -> tuple[str, list[Turn], str | None]:
    """Read bounded question/history; a data-part list wins over metadata.

    Return (question, history, problem); a problem makes the request unusable.
    """
    question = clean_text(get_message_text(message))
    if not question:
        return "", [], "The message has no question text."
    if len(question) > selection.MAX_QUESTION_CHARS:
        return (
            "",
            [],
            f"The question is longer than {selection.MAX_QUESTION_CHARS} characters.",
        )

    turns: list[Turn] = []
    found_in_data_part = False
    for data in get_data_parts(message.parts):
        raw = data.get("history") if isinstance(data, dict) else None
        if isinstance(raw, list):
            found_in_data_part = True
            turns.extend(_turns(raw))
    if not found_in_data_part and isinstance(request_metadata, dict):
        turns = _turns(request_metadata.get("history"))
    return question, turns[-selection.MAX_HISTORY_TURNS :], None


def _candidate(agent: Agent) -> Candidate:
    """Copy an agent row into a ``Candidate`` that is safe to use off-session."""
    return Candidate(
        id=agent.id,
        name=agent.name,
        description=agent.description or "",
        endpoint_url=agent.endpoint_url,
        card_url=agent.card_url,
        skills=agent.skills if isinstance(agent.skills, list) else [],
    )


def load_candidates(session_factory: SessionFactory) -> list[Candidate]:
    """Read the eligible agents. Blocking; run it off the event loop."""
    with session_factory() as db:
        return [
            _candidate(a)
            for a in sorted(routable_agents(db), key=lambda a: (a.name, a.id))
        ]


def reload_candidate(
    session_factory: SessionFactory, agent_id: str
) -> Candidate | None:
    """The agent as it is *now*, or None if it is no longer eligible. Blocking."""
    with session_factory() as db:
        agent = get_routable_agent(db, agent_id)
        return _candidate(agent) if agent is not None else None


class RegistryExecutor(AgentExecutor):
    """Turns an A2A message into a selection and replies with a single Message."""

    def __init__(
        self,
        session_factory: SessionFactory,
        call_llm: LLMCall | None = None,
        limiter: ModelLimiter | None = None,
    ) -> None:
        self._session_factory = session_factory
        # Every model call, real or fake, goes through the concurrency limit.
        self._call_llm = (limiter or ModelLimiter.from_env()).wrap(
            call_llm or selection.default_llm
        )

    async def _decide(self, context: RequestContext) -> SelectionResult:
        question, history, problem = parse_request(context.message, context.metadata)
        if problem:
            log.info("Rejected a selection request: %s", problem)
            return SelectionResult(
                status=selection.ERROR, error_code="invalid_request", retryable=False
            )
        try:
            candidates = await asyncio.to_thread(load_candidates, self._session_factory)
        except SQLAlchemyError:
            log.exception("Could not read the registered agents.")
            return SelectionResult(
                status=selection.ERROR,
                error_code="registry_unavailable",
                retryable=True,
            )
        result = await selection.select_expert(
            question, history, candidates, self._call_llm
        )
        if result.status != selection.SELECTED or result.agent is None:
            return result
        return await self._confirm(result, result.agent)

    async def _confirm(
        self, result: SelectionResult, chosen: Candidate
    ) -> SelectionResult:
        """Re-check the chosen expert just before replying.

        The model can take seconds, during which an admin may revoke, deactivate or
        edit the agent. The reply uses the fresh record, and an agent that is no
        longer eligible is never returned as ``selected``.
        """
        try:
            current = await asyncio.to_thread(
                reload_candidate, self._session_factory, chosen.id
            )
        except SQLAlchemyError:
            log.exception("Could not re-check the selected agent.")
            return SelectionResult(
                status=selection.ERROR,
                error_code="registry_unavailable",
                retryable=True,
            )
        if current is None:
            log.info(
                "Selected agent %s became ineligible; not returning it.", chosen.id
            )
            return SelectionResult(
                status=selection.ERROR, error_code="agent_unavailable", retryable=True
            )
        return replace(result, agent=current)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        try:
            result = await self._decide(context)
        except Exception:
            log.exception("Unexpected failure while selecting an expert.")
            result = SelectionResult(
                status=selection.ERROR, error_code="internal_error", retryable=True
            )
        if result.status == selection.ERROR:
            # A failure is an A2A error carrying only a code, not a reply with a status.
            raise error_for(result)
        await event_queue.enqueue_event(
            new_message(
                parts=[new_text_part(wire_text(result))],
                context_id=context.context_id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Replies are single messages, never long-running tasks, so there is
        # nothing to cancel.
        raise UnsupportedOperationError()
