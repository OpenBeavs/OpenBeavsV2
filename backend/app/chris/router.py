"""Chris discovery route. Application chat routes live in app.chat.router."""

from typing import Any

from fastapi import APIRouter

router = APIRouter()

@router.get("/.well-known/agent.json")
def chris_agent_card() -> dict[str, Any]:
    """Return Chris orchestrator A2A discovery card."""
    return {
        "id": "chris",
        "name": "Chris",
        "description": "OpenBeavs orchestrator. Routes your queries to installed agents and answers directly when no agent matches.",
        "endpoint_url": "/chris/message",
        "card_url": "/chris/.well-known/agent.json",
        "trust_tier": "public",
        "capabilities": {"streaming": True},
        "skills": [
            {
                "id": "route",
                "name": "Route Query",
                "description": "Classify a user query and delegate to the best installed agent.",
                "tags": ["orchestration", "routing"],
            }
        ],
    }
