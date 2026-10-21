"""FastAPI entrypoint. Mounts routers only; contains no feature logic."""

from fastapi import FastAPI

from app.chris.router import router as chris_router

app = FastAPI(title="OpenBeavs v2 (prototype)")

# Unversioned on purpose for the prototype. To version later, change the
# prefix here (for example "/api/v1/chris").
app.include_router(chris_router, prefix="/chris", tags=["chris"])
