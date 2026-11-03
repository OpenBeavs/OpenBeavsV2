"""Build Chris's SDK-backed A2A application and generated discovery card."""

from urllib.parse import urlsplit

from a2a.types import AgentCapabilities
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from starlette.applications import Starlette

from app.chris.agent import chris_agent
from app.config import get_env

MOUNT_PATH = "/chris/a2a"
DEFAULT_PUBLIC_URL = "http://localhost:8000"


async def build_chris_a2a_app() -> Starlette:
    """Generate a card with the public RPC URL, then let ADK handle A2A.

    The parent application must enter this application's lifespan to initialize
    ADK's routes. A2A sessions and tasks use ADK's default in-memory stores.
    """
    public_url = get_env("CHRIS_PUBLIC_URL", DEFAULT_PUBLIC_URL).rstrip("/")
    parsed = urlsplit(public_url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("CHRIS_PUBLIC_URL must be an http(s) base URL.")
    rpc_url = f"{public_url}{MOUNT_PATH}/"
    card = await AgentCardBuilder(
        agent=chris_agent,
        rpc_url=rpc_url,
        capabilities=AgentCapabilities(streaming=False),
        agent_version="0.1.0",
    ).build()
    # ADK strips the trailing slash; ASGI mounts require it at their root.
    # Preserve the exact callable URL so SDK clients need no redirect handling.
    card.supported_interfaces[0].url = rpc_url
    return to_a2a(chris_agent, agent_card=card)
