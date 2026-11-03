"""FastAPI entrypoint. Mounts routers only; contains no feature logic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.chat.router import router as chat_router
from app.chris.router import router as chris_router
from app.registry.auth import check_dev_auth_config
from app.registry.router import router as registry_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Refuse to start if registry development auth is on in a deployment."""
    check_dev_auth_config()
    yield


app = FastAPI(title="OpenBeavs v2 (prototype)", lifespan=lifespan)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Health check endpoint for Cloud Run readiness and local dev."""
    return {"status": "ok", "app": "OpenBeavs v2"}


# Unversioned on purpose for the prototype. To version later, change the
# prefix here (for example "/api/v1/chris").
app.include_router(chat_router, prefix="/chris", tags=["chris"])
app.include_router(chris_router, prefix="/chris", tags=["chris"])
app.include_router(registry_router, prefix="/registry", tags=["registry"])
