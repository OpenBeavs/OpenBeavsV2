"""Run Chris's A2A server as its own process, the only way Chris is served."""

import asyncio
import logging

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from app.chris.a2a import MOUNT_PATH, build_chris_a2a_app
from app.config import env_flag


def create_app() -> Starlette:
    """Chris's agent card and A2A message endpoint, mounted at ``/chris/a2a``.

    The card is generated here, so ``CHRIS_PUBLIC_URL`` is read when the app is
    created. Call this outside a running event loop.
    """
    chris_app = asyncio.run(build_chris_a2a_app())
    return Starlette(routes=[Mount(MOUNT_PATH, app=chris_app)])


def main() -> None:
    """Expose Chris's agent card and A2A message endpoint."""
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app").setLevel(logging.INFO)
    if env_flag("CHRIS_EXPERT_DEBUG"):
        logging.getLogger("app.chris.expert_client").setLevel(logging.DEBUG)
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
