"""Discover and query the standalone registry with the official A2A SDK.

Run from backend: python scripts/registry_a2a_client.py "What majors does OSU offer?"
For an authenticated service set REGISTRY_A2A_TOKEN privately in the environment.
The token and server exception details are never printed.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from a2a.client import ClientConfig, create_client
from a2a.client.errors import A2AClientError
from a2a.helpers import new_message, new_text_part
from a2a.types import Role, SendMessageRequest
from a2a.utils.errors import A2AError

from app.chris.registry_client import _read_reply
from app.chris.routing import SELECTED, InvalidRegistryReply

DEFAULT_URL = "http://127.0.0.1:8001/a2a/registry"


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
                result = _read_reply(event)
                if result.status == SELECTED:
                    return {
                        "agent": {
                            "id": result.agent.id,
                            "endpoint_url": result.agent.endpoint_url,
                        }
                    }
                return {"agent": "none"}
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
