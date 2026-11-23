"""Discover and query the standalone registry with the official A2A SDK.

Run from agent-registry/: uv run python scripts/registry_a2a_client.py "What majors
does OSU offer?" For an authenticated service set REGISTRY_A2A_TOKEN privately in the
environment. The token and server exception details are never printed.

The reply is checked against the registry's documented contract: one text part holding
``{"agent": {"id", "endpoint_url", "name", "description"}}`` or ``{"agent": "none"}``.
"""

import argparse
import asyncio
import json
import os
import sys

import httpx
from a2a.client import ClientConfig, create_client
from a2a.client.errors import A2AClientError
from a2a.helpers import get_text_parts, new_message, new_text_part
from a2a.types import Role, SendMessageRequest, TaskState
from a2a.utils.errors import A2AError

DEFAULT_URL = "http://127.0.0.1:8001/a2a/registry"
AGENT_FIELDS = ("id", "endpoint_url", "name", "description")


class InvalidRegistryReply(ValueError):
    """The registry's reply did not match the documented contract."""


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def parse_reply(text: str) -> dict:
    """Return the selection in the reply's text, or raise InvalidRegistryReply."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        raise InvalidRegistryReply("The registry reply is not JSON.") from None
    if not isinstance(data, dict) or set(data) != {"agent"}:
        raise InvalidRegistryReply("The registry reply is not valid.")
    agent = data["agent"]
    if agent == "none":
        return {"agent": "none"}
    if (
        isinstance(agent, dict)
        and set(agent) == set(AGENT_FIELDS)
        and _is_text(agent["id"])
        and _is_text(agent["endpoint_url"])
        # A blank name is the registry's record as it stands, not a malformed reply.
        and isinstance(agent["name"], str)
        and (agent["description"] is None or isinstance(agent["description"], str))
    ):
        return {"agent": {field: agent[field] for field in AGENT_FIELDS}}
    raise InvalidRegistryReply("The registry reply is not valid.")


def read_reply(event) -> dict:
    """Extract the selection from one SDK response (its text part holds the JSON)."""
    if event.HasField("message"):
        parts = list(event.message.parts)
    elif (
        event.HasField("task")
        and event.task.status.state == TaskState.TASK_STATE_COMPLETED
    ):
        parts = [p for artifact in event.task.artifacts for p in artifact.parts]
    else:
        raise A2AError("The registry did not complete selection.")
    texts = [t for t in get_text_parts(parts) if t.strip()]
    if len(texts) != 1:
        raise InvalidRegistryReply("Expected exactly one text part.")
    return parse_reply(texts[0])


async def ask(url: str, question: str, token: str | None) -> dict:
    """Return the validated compact text-JSON selection; never print credentials."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(
        headers=headers, timeout=14, follow_redirects=False, trust_env=False
    ) as http:
        client = await create_client(
            url, ClientConfig(httpx_client=http, streaming=False)
        )
        try:
            request = SendMessageRequest(
                message=new_message(
                    parts=[new_text_part(question)], role=Role.ROLE_USER
                )
            )
            async for event in client.send_message(request):
                return read_reply(event)
        finally:
            await client.close()
    raise RuntimeError("The registry sent no message.")


def main() -> int:
    """Print a compact selection or a generic failure without internal details."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--url", default=DEFAULT_URL, help="registry base A2A URL")
    args = parser.parse_args()
    try:
        data = asyncio.run(
            ask(args.url, args.question, os.getenv("REGISTRY_A2A_TOKEN"))
        )
    except (
        httpx.HTTPError,
        A2AClientError,
        A2AError,
        InvalidRegistryReply,
        TimeoutError,
        ValueError,
        RuntimeError,
    ):
        print("Registry request failed.", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
