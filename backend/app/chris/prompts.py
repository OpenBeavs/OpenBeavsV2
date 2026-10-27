"""Chris's direct-answer system prompt."""

from app.chris.agents import Agent

# Adapted from the v1 direct-answer prompt. The installed-agents list is
# injected so Chris never invents agents.
_DIRECT_PROMPT_BASE = (
    "You are Chris, the OpenBeavs AI hub assistant. "
    "You are answering the user directly; there is no agent being called right now. "
    "NEVER invent or guess agent names. Only refer to agents that appear in the "
    "INSTALLED AGENTS list below. If the list is empty, say the user has no agents installed."
)


def build_direct_prompt(agents: list[Agent]) -> str:
    """Return the direct-answer prompt with the real installed-agent list."""
    if agents:
        lines = "\n".join(
            f"- {a.name}" + (f": {a.description}" if a.description else "")
            for a in agents
        )
        section = f"\n\nINSTALLED AGENTS:\n{lines}"
    else:
        section = "\n\nINSTALLED AGENTS: none"
    return _DIRECT_PROMPT_BASE + section
