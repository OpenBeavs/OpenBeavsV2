"""Shared helpers for the registry A2A tests.

``Harness`` mounts the registry's A2A app the way the real backend does and gives
tests an official A2A SDK client pointed at it, so a real client (standing in for
Chris) talks to the registry without any network.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers import (
    get_text_parts,
    new_data_part,
    new_message,
    new_text_part,
)
from a2a.types import Role, SendMessageRequest
from a2a.utils.errors import A2AError
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app.models import Agent
from app.registry.a2a import MOUNT_PATH, RETRYABLE
from app.registry.a2a_app import create_registry_a2a_app
from app.registry.a2a_auth import Verifier, open_verifier
from app.registry.llm import ModelLimiter

BASE = "http://registry.test"


def run(coro: Awaitable[Any]) -> Any:
    """Run one async scenario to completion."""
    return asyncio.run(coro)  # type: ignore[arg-type]


def add_agent(
    db: Session,
    agent_id: str,
    *,
    status: str = "approved",
    active: bool = True,
    tier: str = "public",
    role: str | None = None,
    description: str | None = None,
    skills: list | None = None,
) -> Agent:
    """Insert an agent row directly with the given review state."""
    agent = Agent(
        id=agent_id,
        name=agent_id.replace("-", " ").title(),
        description=description or f"The {agent_id} expert.",
        endpoint_url=f"https://{agent_id}.example.test/rpc",
        card_url=f"https://{agent_id}.example.test/.well-known/agent.json",
        trust_tier=tier,
        required_role=role,
        skills=skills
        if skills is not None
        else [{"name": f"{agent_id} skill", "tags": [agent_id]}],
        is_active=active,
        status=status,
    )
    db.add(agent)
    db.commit()
    return agent


def llm_choosing(
    agent_id: str, confidence: float = 0.95, reason: str = "It fits."
) -> Callable[[str, str, dict], Awaitable[str]]:
    """A fake model that always picks ``agent_id``; records what it was asked."""

    async def call(system: str, user: str, schema: dict) -> str:
        call.calls.append((system, user, schema))  # type: ignore[attr-defined]
        return json.dumps(
            {"agent_id": agent_id, "confidence": confidence, "reason": reason}
        )

    call.calls = []  # type: ignore[attr-defined]
    return call


class Harness:
    """The registry A2A app mounted at its real path, plus an SDK client."""

    def __init__(
        self,
        db: Session,
        call_llm: Callable[[str, str, dict], Awaitable[str]] | None = None,
        verifier: Verifier = open_verifier,
        session_factory: Callable[[], Session] | None = None,
        limiter: ModelLimiter | None = None,
    ) -> None:
        factory = session_factory or sessionmaker(
            bind=db.get_bind(), expire_on_commit=False
        )
        self.root = FastAPI()
        self.root.mount(
            MOUNT_PATH,
            create_registry_a2a_app(
                base_url=BASE,
                verifier=verifier,
                session_factory=factory,
                call_llm=call_llm,
                limiter=limiter,
            ),
        )

    def http(self, **kwargs: Any) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.root), base_url=BASE, **kwargs
        )

    async def ask(
        self,
        question: str,
        history: list[dict] | None = None,
        http=None,
        metadata: dict | None = None,
    ) -> tuple[str, dict]:
        """Send a question with the official SDK client; return (text, data part)."""
        own = http is None
        http = http or self.http()
        try:
            client = await create_client(
                f"{BASE}{MOUNT_PATH}", ClientConfig(httpx_client=http, streaming=False)
            )
            parts = [new_text_part(question)]
            if history is not None:
                parts.append(new_data_part({"history": history}))
            request = SendMessageRequest(
                message=new_message(parts=parts, role=Role.ROLE_USER)
            )
            if metadata is not None:
                request.metadata.update(metadata)
            replies = [event async for event in client.send_message(request)]
        except A2AError as error:
            # A failed selection is an A2A error whose message is the code, nothing else.
            code = error.message
            assert code in RETRYABLE, f"not a coded registry error: {error!r}"
            return "", {
                "status": "error",
                "agent": None,
                "error": {"code": code, "retryable": RETRYABLE[code]},
            }
        finally:
            if own:
                await http.aclose()
        assert len(replies) == 1 and replies[0].HasField("message")
        message = replies[0].message
        # The reply is exactly one text part holding the JSON Chris reads, nothing else.
        assert [p.WhichOneof("content") for p in message.parts] == ["text"]
        text = get_text_parts(message.parts)[0]
        wire = json.loads(text)
        assert list(wire) == ["agent"]
        if wire["agent"] == "none":
            return text, {"status": "no_match", "agent": None, "error": None}
        assert set(wire["agent"]) == {"id", "endpoint_url"}
        return text, {"status": "selected", "agent": wire["agent"], "error": None}


def rpc(method: str, params: dict, request_id: Any = 1) -> dict:
    """A raw JSON-RPC envelope."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def v1_message(text: str = "hello") -> dict:
    """The params of a raw A2A 1.0 SendMessage."""
    return {
        "message": {
            "role": "ROLE_USER",
            "messageId": "m-1",
            "parts": [{"text": text}],
        }
    }
