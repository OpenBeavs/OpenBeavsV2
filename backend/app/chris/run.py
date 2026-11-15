"""Run Chris's A2A server independently of the main application."""

import asyncio
import logging

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from app.chris.a2a import MOUNT_PATH, build_chris_a2a_app
from app.config import env_flag


def main() -> None:
    """Expose Chris's agent card and A2A message endpoint."""
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app").setLevel(logging.INFO)
    if env_flag("CHRIS_EXPERT_DEBUG"):
        logging.getLogger("app.chris.expert_client").setLevel(logging.DEBUG)
    chris_app = asyncio.run(build_chris_a2a_app())
    app = Starlette(routes=[Mount(MOUNT_PATH, app=chris_app)])
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
