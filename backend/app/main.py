"""FastAPI entrypoint. Mounts routers only; contains no feature logic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Mount

from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.chris.a2a import MOUNT_PATH, build_chris_a2a_app
from app.registry.auth import check_dev_auth_config
from app.registry.router import router as registry_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Check registry auth and initialize Chris's isolated A2A endpoint."""
    check_dev_auth_config()
    chris_app = await build_chris_a2a_app()
    mount = Mount(MOUNT_PATH, app=chris_app)
    # Keep the mounted app's lifespan aligned with the parent application's.
    async with chris_app.router.lifespan_context(chris_app):
        app.router.routes.append(mount)
        try:
            yield
        finally:
            app.router.routes.remove(mount)


app = FastAPI(title="OpenBeavs v2 (prototype)", lifespan=lifespan)

# Allow cross-origin requests from SvelteKit frontend (dev & OSU production domains)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:[0-9]+)?|https://.*\.oregonstate\.edu",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Health check endpoint for Cloud Run readiness and local dev."""
    return {"status": "ok", "app": "OpenBeavs v2"}


# Mount domain routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(registry_router, prefix="/registry", tags=["registry"])
