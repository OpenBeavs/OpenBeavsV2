"""FastAPI entrypoint. Mounts routers only; contains no feature logic."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.chris.router import router as chris_router

app = FastAPI(title="OpenBeavs v2 (prototype)")

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


# Unversioned on purpose for the prototype. To version later, change the
# prefix here (for example "/api/v1/chris").
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(chris_router, prefix="/chris", tags=["chris"])
