"""Run Chris's A2A server independently of the main application."""

import asyncio
import logging

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from app.chris.a2a import MOUNT_PATH, build_chris_a2a_app


def main() -> None:
    """Expose Chris's agent card and A2A message endpoint."""
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app").setLevel(logging.INFO)
    chris_app = asyncio.run(build_chris_a2a_app())
    app = Starlette(routes=[Mount(MOUNT_PATH, app=chris_app)])
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
