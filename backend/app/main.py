"""FastAPI entrypoint. Mounts routers only; contains no feature logic."""

from fastapi import FastAPI

from app.chris.router import router as chris_router
from app.registry.router import router as registry_router

app = FastAPI(title="OpenBeavs v2 (prototype)")


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Health check endpoint for Cloud Run readiness and local dev."""
    return {"status": "ok", "app": "OpenBeavs v2"}


# Unversioned on purpose for the prototype. To version later, change the
# prefix here (for example "/api/v1/chris").
app.include_router(chris_router, prefix="/chris", tags=["chris"])
app.include_router(registry_router, prefix="/registry", tags=["registry"])
