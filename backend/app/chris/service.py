"""Chris's direct-answer behavior, independent of HTTP and chat storage."""

from app.chris.agents import Agent
from app.chris.llm import generate
from app.chris.prompts import build_direct_prompt


async def answer_direct(
    message: str, history: list[dict[str, str]], agents: list[Agent]
) -> str:
    """Answer with the existing prompt, supplied history, and configured model."""
    messages = [
        {"role": "system", "content": build_direct_prompt(agents)},
        *history,
        {"role": "user", "content": message},
    ]
    return await generate(messages)
