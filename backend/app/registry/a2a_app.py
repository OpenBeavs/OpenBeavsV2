"""Standalone registry A2A app, public discovery, authentication and health probes.

The main Chat/Chris backend does not mount this service. Start it separately with
uvicorn app.registry.a2a_app:create_standalone_app --factory.
"""

import logging
from urllib.parse import urlsplit

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import ConfigError, get_env
from app.models import Agent
from app.registry.a2a import (
    MOUNT_PATH,
    RegistryExecutor,
    SessionFactory,
    build_agent_card,
)
from app.registry.a2a_auth import (
    A2AAuthMiddleware,
    Verifier,
    auth_config_problem,
    build_verifier,
)
from app.registry.llm import LLMCall, ModelLimiter

log = logging.getLogger(__name__)

OK, FAILED = "ok", "failed"

LOCAL_BASE_URL = "http://127.0.0.1:8000"


def validate_origin(url: str, *, require_https: bool) -> str:
    """Validate the advertised origin/token audience without echoing its value.

    Reject credentials, paths, queries, fragments and ambiguous URL characters.
    Cloud Run additionally requires HTTPS. Raises ConfigError on invalid input.
    """
    problem = "REGISTRY_PUBLIC_URL must be an origin like https://host (no path)."
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c == "\\" for c in url):
        raise ConfigError(problem)
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        raise ConfigError(problem) from None
    allowed = {"https"} if require_https else {"https", "http"}
    if parts.scheme not in allowed or not host:
        raise ConfigError(problem + (" It must use https." if require_https else ""))
    if parts.username is not None or parts.password is not None:
        raise ConfigError(problem)
    if parts.path not in ("", "/") or parts.query or parts.fragment or "?" in url:
        raise ConfigError(problem)
    return f"{parts.scheme}://{parts.netloc}"


def public_base_url() -> str:
    """Return the configured bare origin; require an explicit HTTPS origin on Cloud Run.

    Local fallback is http://127.0.0.1:8000. Invalid settings raise ConfigError.
    """
    on_cloud_run = bool(get_env("K_SERVICE"))
    url = get_env("REGISTRY_PUBLIC_URL")
    if url:
        return validate_origin(url, require_https=on_cloud_run)
    if on_cloud_run:
        raise ConfigError(
            "REGISTRY_PUBLIC_URL is not set. Set it to this service's public URL."
        )
    return LOCAL_BASE_URL


class _Unavailable:
    """Stand-in app that answers 503 when the registry cannot start safely."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            await JSONResponse(
                {"detail": "The registry A2A agent is not configured."}, 503
            )(scope, receive, send)


def create_registry_a2a_app(
    *,
    base_url: str | None = None,
    verifier: Verifier | None = None,
    session_factory: SessionFactory | None = None,
    call_llm: LLMCall | None = None,
    limiter: ModelLimiter | None = None,
) -> ASGIApp:
    """Create the A2A app. Arguments are for tests; defaults come from the environment."""
    try:
        base = base_url or public_base_url()
    except ConfigError as e:
        log.error("Registry A2A agent disabled: %s", e)
        return _Unavailable(str(e))

    if session_factory is None:
        from app.db import SessionLocal

        session_factory = SessionLocal

    card = build_agent_card(base)
    handler = DefaultRequestHandler(
        agent_executor=RegistryExecutor(session_factory, call_llm, limiter),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    app = FastAPI(
        title="OpenBeavs Agent Registry (A2A)",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=[
            *create_agent_card_routes(card, card_url="/.well-known/agent-card.json"),
            *create_agent_card_routes(card, card_url="/.well-known/agent.json"),
        ],
        # enable_v0_3_compat: the same endpoint also answers 0.3 clients that send
        # "A2A-Version: 0.3", so the caller's A2A version is not a blocker.
        jsonrpc_routes=create_jsonrpc_routes(
            handler, rpc_url="/", enable_v0_3_compat=True
        ),
    )
    app.add_middleware(A2AAuthMiddleware, verifier=verifier or build_verifier(base))
    return app


def create_standalone_app(
    session_factory: SessionFactory | None = None,
) -> FastAPI:
    """The registry A2A agent on its own, for running as a separate service.

    ``/health`` is liveness (the process answers). ``/ready`` is readiness: it checks
    the database and required configuration, never calls Gemini, and answers 503
    until everything a request needs is in place. Neither route needs a token.
    """
    if session_factory is None:
        from app.db import SessionLocal

        session_factory = SessionLocal
    try:
        base: str | None = public_base_url()
    except ConfigError:
        base = None  # create_registry_a2a_app logs this and serves 503s

    root = FastAPI(title="OpenBeavs Agent Registry", docs_url=None, redoc_url=None)

    @root.get("/health")
    def health() -> dict[str, str]:
        """Liveness check for Cloud Run."""
        return {"status": "ok", "app": "OpenBeavs Agent Registry"}

    @root.get("/ready")
    def ready() -> JSONResponse:
        """Readiness check: database and configuration, with no paid model call."""
        checks = run_checks(session_factory, base)
        is_ready = FAILED not in checks.values()
        return JSONResponse(
            {"status": "ready" if is_ready else "not_ready", "checks": checks},
            status_code=200 if is_ready else 503,
        )

    root.mount(
        MOUNT_PATH,
        create_registry_a2a_app(base_url=base, session_factory=session_factory),
    )
    return root


def _database(session_factory: SessionFactory) -> bool:
    """Read one row's worth of every column the registry's selection query uses."""
    try:
        with session_factory() as db:
            db.execute(
                select(
                    Agent.id,
                    Agent.status,
                    Agent.is_active,
                    Agent.trust_tier,
                    Agent.required_role,
                    Agent.endpoint_url,
                ).limit(1)
            ).all()
    except SQLAlchemyError as e:
        # The type only: the message can carry the host, user or SQL.
        log.error("Readiness: the agents table is not usable (%s).", type(e).__name__)
        return False
    return True


def run_checks(session_factory: SessionFactory, base_url: str | None) -> dict[str, str]:
    """Check readiness without paid calls or exposing setting values."""
    checks = {"database": OK if _database(session_factory) else FAILED}
    checks["public_url"] = OK if base_url is not None else FAILED
    if base_url is None:
        log.error("Readiness: REGISTRY_PUBLIC_URL is not set.")
    problem = auth_config_problem(base_url or "")
    checks["auth"] = FAILED if problem else OK
    if problem:
        log.error("Readiness: A2A authentication is unusable: %s", problem)
    for check, names in {
        "model": ("REGISTRY_MODEL",),
        "model_key": ("REGISTRY_GEMINI_API_KEY", "GEMINI_API_KEY"),
    }.items():
        present = any(get_env(name) for name in names)
        checks[check] = OK if present else FAILED
        if not present:
            log.error("Readiness: configure %s.", " or ".join(names))
    return checks
