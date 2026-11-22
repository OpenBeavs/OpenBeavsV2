"""FastAPI entrypoint. Mounts routers only; contains no feature logic."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.chat.router import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging. Chris runs as its own process (``conversation_agent.run``)."""
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app").setLevel(logging.INFO)
    yield


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

# Compatibility alias for Azure Entra ID registered callback path (/oauth/microsoft/callback)
from app.auth.router import oauth_callback

app.add_api_route(
    "/oauth/microsoft/callback",
    oauth_callback,
    methods=["GET"],
    include_in_schema=False,
)
