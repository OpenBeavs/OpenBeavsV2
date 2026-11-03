"""FastAPI entrypoint. Mounts routers only; contains no feature logic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.routing import Mount

from app.chat.router import router as chat_router
from app.chris.a2a import MOUNT_PATH, build_chris_a2a_app
from app.registry.auth import check_dev_auth_config
from app.registry.router import router as registry_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Check registry auth and initialize the mounted ADK application's routes."""
    check_dev_auth_config()
    chris_app = await build_chris_a2a_app()
    mount = Mount(MOUNT_PATH, app=chris_app)
    # Mounted sub-app lifespans are not entered automatically by FastAPI.
    async with chris_app.router.lifespan_context(chris_app):
        app.router.routes.append(mount)
        try:
            yield
        finally:
            app.router.routes.remove(mount)


app = FastAPI(title="OpenBeavs v2 (prototype)", lifespan=lifespan)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Health check endpoint for Cloud Run readiness and local dev."""
    return {"status": "ok", "app": "OpenBeavs v2"}


# Unversioned on purpose for the prototype. To version later, change the
# prefix here (for example "/api/v1/chris").
app.include_router(chat_router, prefix="/chris", tags=["chris"])
app.include_router(registry_router, prefix="/registry", tags=["registry"])
