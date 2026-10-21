"""Agent routing decision for Chris (not yet wired into the HTTP route).

Two layers keep the decision safe:
1. The model is constrained to a JSON schema whose ``agent_id`` is an enum of
   the installed agent ids plus "none", so it cannot reply with free text or an
   invented id.
2. The reply is parsed and validated again here (known id, confidence
   threshold). Any failure falls back to "none" (Chris answers directly).

This guarantees a well-formed, allowed choice. It does not guarantee the
choice is the *right* agent; measure that with a labeled test set.
"""

import json
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

from app.chris.llm import LLMError, generate

log = logging.getLogger(__name__)

NONE_ID = "none"

# Picks below this confidence fall back to a direct answer. 0.7 is an initial
# guess, not a measured value; tune it against labeled routing examples.
CONFIDENCE_THRESHOLD = 0.7


@dataclass
class Agent:
    """The minimum agent metadata the router needs."""

    id: str
    name: str
    description: str = ""
    skills: list[str] = field(default_factory=list)


class RoutingDecision(BaseModel):
    """The validated shape of the model's routing reply."""

    agent_id: str
    confidence: float = Field(
        ge=0.0, le=1.0, description="Certainty from 0 to 1 that this is the right choice."
    )
    reason: str = Field(description="One short sentence.")


def _build_schema(agent_ids: list[str]) -> dict:
    """Build the response schema from ``RoutingDecision`` (one definition for both).

    ``agent_id`` is narrowed to an enum of the installed ids plus "none" for
    this request, so the model cannot return an id that is not installed.
    """
    schema = RoutingDecision.model_json_schema()
    schema["properties"]["agent_id"]["enum"] = [*agent_ids, NONE_ID]
    return schema


def _build_system_prompt(agents: list[Agent]) -> str:
    """Describe the agents and the routing rules (adapted from the v1 router prompt)."""
    lines = "\n".join(
        f"- id={a.id!r}: name={a.name!r}, description={a.description or 'none'!r}, "
        f"skills={a.skills}"
        for a in agents
    )
    return (
        "You are a strict router for the OpenBeavs hub. Decide whether one of the "
        "agents below is the RIGHT tool for the user's message.\n\n"
        f"Agents:\n{lines}\n\n"
        "Rules:\n"
        "1. Choose an agent only if its skills or description SPECIFICALLY and CLEARLY "
        "match the user's intent, not just a vague overlap.\n"
        f"2. Use {NONE_ID!r} for greetings, small talk, thanks, jokes, general questions, "
        "anything you can answer directly, or when you are not certain.\n"
        "3. Give your honest confidence from 0 to 1."
    )


async def choose_agent(message: str, agents: list[Agent]) -> Agent | None:
    """Return the agent that should handle ``message``, or None to answer directly.

    Never raises for model or parsing problems (they log and return None).
    Configuration errors still propagate so they are not silently hidden.
    """
    if not agents:
        return None

    by_id = {a.id: a for a in agents}
    messages = [
        {"role": "system", "content": _build_system_prompt(agents)},
        {"role": "user", "content": message},
    ]

    try:
        raw = await generate(messages, response_schema=_build_schema(list(by_id)))
        decision = RoutingDecision.model_validate(json.loads(raw))
    except (LLMError, ValueError, ValidationError) as e:
        # ValueError covers json.JSONDecodeError.
        log.warning("Routing decision failed, answering directly: %s", e)
        return None

    log.info(
        "Routing decision: agent=%s confidence=%.2f reason=%s",
        decision.agent_id, decision.confidence, decision.reason,
    )

    if decision.agent_id == NONE_ID:
        return None
    agent = by_id.get(decision.agent_id)
    if agent is None:
        log.warning("Model returned unknown agent id %r; answering directly.", decision.agent_id)
        return None
    if decision.confidence < CONFIDENCE_THRESHOLD:
        log.info("Confidence below threshold; answering directly.")
        return None
    return agent
