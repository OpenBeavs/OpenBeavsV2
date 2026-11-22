"""Serve Chris's A2A agent as its own process, the only way Chris is served.

Two routes serve the same application:

- ``python -m app.chris.run`` binds ``127.0.0.1:8000``, for local development.
- ``uvicorn app.chris.run:create_app --factory --host <host> --port <port>`` binds the
  address the deployer chooses.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from app.chris.a2a import MOUNT_PATH, build_chris_a2a_app
from app.config import env_flag


def _build_a2a_app() -> Starlette:
    """Run the asynchronous card builder to completion from synchronous code."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(build_chris_a2a_app())
    # uvicorn calls a --factory inside its running event loop, where asyncio.run() is
    # refused. Build on a worker thread with a loop of its own; the application it
    # returns holds no reference to the loop that built it.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(build_chris_a2a_app())).result()


def create_app() -> Starlette:
    """Chris's agent card and A2A message endpoint, mounted at ``/chris/a2a``.

    The card is generated here, so ``CHRIS_PUBLIC_URL`` is read when the app is
    created. It may be called with or without a running event loop, so it works as a
    ``uvicorn --factory`` target.
    """
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app").setLevel(logging.INFO)
    if env_flag("CHRIS_EXPERT_DEBUG"):
        logging.getLogger("app.chris.expert_client").setLevel(logging.DEBUG)
    return Starlette(routes=[Mount(MOUNT_PATH, app=_build_a2a_app())])


def main() -> None:
    """Serve Chris on the local development address."""
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
