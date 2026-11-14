"""The whole pipeline with a FAKE registry model, for deterministic browser tests.

Starts, on loopback only:

- the registry A2A service (real code) on 127.0.0.1:8101, with a scripted stand-in for
  Gemini and the registry's local-development mode (no authentication);
- the Chat + Chris backend (real code) on 127.0.0.1:8100, pointed at that registry.

Both use a fresh temporary SQLite database with three experts. No Gemini key is read
(``PYTHON_DOTENV_DISABLED`` stops ``.env`` from loading). Expert dispatch and Gemini
fallback use scripted replies.
This proves the plumbing and the user interface; it says nothing about how the real model
behaves. For that use the real-model stack in the README.

The scripted model looks at the latest question:

=============  ===========================================================
contains       model behavior
=============  ===========================================================
``math``       picks ``math-expert`` (confidence 0.93)
``osu``        picks ``osu-expert`` (0.9)
``followup``   picks ``osu-expert`` ONLY if it was given an earlier user turn (history
               reached the registry); with no history it finds no match
``weak``       picks ``math-expert`` at 0.4 (below the threshold: no match)
``break``      raises a model error (``selection_unavailable``)
``garbage``    returns text that is not JSON (``invalid_model_reply``)
``slow``       takes 6 s, longer than Chris's 3 s deadline (``registry_timeout``)
``revoke``     revokes ``flaky-expert`` while "thinking" and then picks it
               (``agent_unavailable``); it is restored 1.5 s later
anything else  no match
=============  ===========================================================

Run from ``backend/``::

    .venv\\Scripts\\python.exe scripts\\fake_model_stack.py
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

# Run as a script from anywhere: make the backend package importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Configure before importing the app: settings are read at import and call time.
_tmp = tempfile.mkdtemp(prefix="openbeavs-fake-stack-")
os.environ.update(
    {
        "PYTHON_DOTENV_DISABLED": "1",
        "DATABASE_URL": f"sqlite:///{Path(_tmp, 'stack.db').as_posix()}",
        "CHRIS_PUBLIC_URL": "http://127.0.0.1:8100",
        "CHRIS_A2A_URL": "http://127.0.0.1:8100/chris/a2a/",
        "REGISTRY_A2A_URL": "http://127.0.0.1:8101/a2a/registry",
        "REGISTRY_A2A_TIMEOUT_SECONDS": "3",
        "CHRIS_A2A_TIMEOUT_SECONDS": "10",
    }
)
for name in ("REGISTRY_A2A_AUTH", "K_SERVICE", "GEMINI_API_KEY", "CHRIS_MODEL"):
    os.environ.pop(name, None)

import uvicorn
from fastapi import FastAPI

from app.chris import expert_client, gemini
from app.db import SessionLocal, engine
from app.db.base import Base
from app.main import app as backend_app
from app.models import Agent
from app.registry.a2a import MOUNT_PATH
from app.registry.a2a_app import create_registry_a2a_app
from app.registry.a2a_auth import open_verifier
from app.registry.llm import LLMError, ModelLimiter

REGISTRY_PORT, BACKEND_PORT = 8101, 8100


def seed() -> None:
    """Three eligible experts. Their endpoints are placeholders and are never called."""
    Base.metadata.create_all(bind=engine)
    rows = [
        ("math-expert", "Math Expert", "Arithmetic, percentages and unit conversions."),
        ("osu-expert", "OSU Expert", "Questions about Oregon State University."),
        ("flaky-expert", "Flaky Expert", "Used to test an expert revoked mid-selection."),
    ]
    with SessionLocal() as db:
        for agent_id, name, description in rows:
            db.add(
                Agent(
                    id=agent_id,
                    name=name,
                    description=description,
                    endpoint_url=f"https://{agent_id}.example.test/a2a/",
                    card_url=f"https://{agent_id}.example.test/card.json",
                    trust_tier="public",
                    skills=[{"name": name, "tags": [agent_id]}],
                    is_active=True,
                    status="approved",
                )
            )
        db.commit()


def _set_flaky(active: bool) -> None:
    with SessionLocal() as db:
        agent = db.get(Agent, "flaky-expert")
        agent.is_active = active
        agent.status = "approved" if active else "revoked"
        db.commit()


def _reply(agent_id: str, confidence: float, reason: str) -> str:
    return json.dumps(
        {"agent_id": agent_id, "confidence": confidence, "reason": reason}
    )


async def scripted_model(system: str, user: str, schema: dict) -> str:
    """A stand-in for Gemini, driven by keywords in the latest question."""
    latest = user.rsplit("select an agent for this):\n", 1)[-1].lower()
    if "break" in latest:
        raise LLMError("Gemini request failed with HTTP 503.")
    if "garbage" in latest:
        return "definitely not json"
    if "slow" in latest:
        await asyncio.sleep(6)
        return _reply("none", 0.9, "Too late to matter.")
    if "revoke" in latest:
        _set_flaky(False)
        threading.Timer(1.5, _set_flaky, args=(True,)).start()
        return _reply("flaky-expert", 0.97, "Looks like the flaky expert's topic.")
    if "followup" in latest:
        has_history = any(line.startswith("user: ") for line in user.splitlines())
        if has_history:
            return _reply("osu-expert", 0.9, "A follow-up to the earlier OSU question.")
        return _reply("none", 0.9, "No earlier turn to resolve this follow-up.")
    if "weak" in latest:
        return _reply("math-expert", 0.4, "Only a vague overlap.")
    if "math" in latest or "percent" in latest:
        return _reply("math-expert", 0.93, "An arithmetic question.")
    if "osu" in latest:
        return _reply("osu-expert", 0.9, "About Oregon State University.")
    return _reply("none", 0.9, "Nothing registered fits.")


def serve(app, port: int) -> uvicorn.Server:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    return server


async def scripted_expert(endpoint: str, message: str, history: list[dict[str, str]]) -> str:
    return "Expert answer."


async def scripted_fallback(message: str, history: list[dict[str, str]]) -> str:
    if any(word in message.lower() for word in ("break", "garbage", "slow", "revoke")):
        raise gemini.GeminiUnavailable("Scripted fallback failure.")
    return "Gemini answer."


def main() -> int:
    expert_client.send_message = scripted_expert
    gemini.answer = scripted_fallback
    seed()
    registry = FastAPI()
    registry.mount(
        MOUNT_PATH,
        create_registry_a2a_app(
            base_url=f"http://127.0.0.1:{REGISTRY_PORT}",
            verifier=open_verifier,
            session_factory=SessionLocal,
            call_llm=scripted_model,
            limiter=ModelLimiter(8, 2),
        ),
    )
    serve(registry, REGISTRY_PORT)
    serve(backend_app, BACKEND_PORT)
    print(
        f"Fake-model stack ready: backend http://127.0.0.1:{BACKEND_PORT}, "
        f"registry http://127.0.0.1:{REGISTRY_PORT} (database in {_tmp})",
        flush=True,
    )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
