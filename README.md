# OpenBeavs v2

The OSU AI hub prototype, with a standalone Chris frontend and FastAPI backend.

- `frontend/`: Svelte chat interface.
- `backend/`: chat REST API, sign-in, and persistence.
- `chat-system/`: the OpenBeavs Chat System. `chat-system/conversation-agent/` holds Chris, the Conversation Agent (an ADK agent served over A2A), a Python package with its own environment, run as its own service.
- `agent-registry/`: the Agent Registry (expert selection over A2A, and registry management), a Python package with its own environment, database and migrations, run as its own service.
- `docs/`: API, frontend setup, and database documentation.

Start with local setup for [macOS](#run-locally-macos) or
[Windows](#run-locally-windows-powershell), then see
[Chris's API](chat-system/conversation-agent/README.md). Chat calls Chris over A2A; Chris asks the standalone
registry to select an expert. By default Chris answers with Gemini when no expert
matches or the registry fails. Selected public
HTTPS experts are invoked over A2A (0.3 by default; configure
`CHRIS_EXPERT_A2A_VERSION=1.0` for 1.0 experts). Verified SSO and
service-to-service authentication remain future work.

For Agent Registry behavior, local setup, and testing, see [Agent Registry documentation](agent-registry/README.md).

## Run locally (macOS)

Use uv and Node.js 22 or later. If uv is missing, install it with `brew install uv`.
From the repository root, set up the dependencies once:

```zsh
cd agent-registry
uv sync --locked --python 3.12
cd ../chat-system/conversation-agent
uv sync --locked --python 3.12
cd ../../backend
uv sync --locked --python 3.12
cd ..
[ -f .env ] || cp .env.example .env
cd frontend
npm ci
cd ..
```

In `.env` at the repository root, set `GEMINI_API_KEY`, `CHRIS_MODEL`, and `REGISTRY_MODEL`
privately. Set `REGISTRY_GEMINI_API_KEY` if the registry uses a separate key.
For local registry development, set `REGISTRY_A2A_AUTH=dev`. Set
`REGISTRY_DEV_AUTH=true` and configure `REGISTRY_ADMIN_EMAILS` only if you need
local registry admin actions.

Initialize the local databases before the first run, and rerun migrations when
the schema changes. The registry and the chat backend each keep their own:

```zsh
export DATABASE_URL='sqlite:///./openbeavs.db'
cd agent-registry
uv run alembic upgrade head
uv run python -m agent_registry.db.seed_agents
cd ../backend
uv run alembic upgrade head
cd ..
```

Start all four services from the repository root:

```zsh
bash start-dev-mac.sh
```

Open [OpenBeavs](http://127.0.0.1:5173). The script runs all four services in one
terminal. The registry uses `agent-registry/openbeavs.db`, and Chat uses
`backend/openbeavs.db`; Chris has no database. Press **Ctrl+C** there to stop them.

## Run locally (Windows PowerShell)

Use Python 3.12 and Node.js 22 or later. For first-time dependency setup, run from
the repository root:

```powershell
cd .\agent-registry
py -3.12 -m venv .venv
# --group needs pip 25.1 or later.
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e . --group dev
cd ..\chat-system\conversation-agent
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e . --group dev
cd ..\..\backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ..\agent-registry -e ..\chat-system\conversation-agent -e . -r requirements-dev.txt
cd ..
if (!(Test-Path .env)) { Copy-Item .env.example .env }
cd .\frontend
npm install
cd ..
```

Edit the ignored `.env` at the repository root privately. Configure `CHRIS_MODEL` and
`GEMINI_API_KEY` for Chris, and `REGISTRY_MODEL` and `REGISTRY_GEMINI_API_KEY`
for registry selection. Set `REGISTRY_DEV_AUTH=true` and `REGISTRY_A2A_AUTH=dev`
only for local development. For local registry admin actions, set
`REGISTRY_ADMIN_EMAILS` to your chosen development identity. Never commit keys.
Virtual environment activation is not required for the commands below.

### 1. Create or update the local databases

The registry and the chat backend each keep their own database. Open PowerShell in the
repository root (`OpenBeavsV2`), then create the registry's:

```powershell
cd .\agent-registry
$env:DATABASE_URL = 'sqlite:///./openbeavs.db'
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Wait for the command to finish successfully, then seed the standard registered agents:

```powershell
.\.venv\Scripts\python.exe -m agent_registry.db.seed_agents
```

Then create the chat backend's:

```powershell
cd ..\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

This creates or updates `agent-registry/openbeavs.db` and `backend/openbeavs.db`. SQLite does not require a separate
database server. Migrations apply pending schema changes; rerunning the seed preserves
existing agents. Setting `DATABASE_URL` explicitly ensures this session uses
`openbeavs.db` rather than another configured file such as `registry-local.db`.

### 2. Start all four services

In the **same PowerShell terminal**, still inside `backend/`, run:

```powershell
.\.venv\Scripts\python.exe ..\start-dev.py
```

Alternatively, from the repository root:

```powershell
$env:DATABASE_URL = 'sqlite:///./openbeavs.db'
.\backend\.venv\Scripts\python.exe .\start-dev.py
```

The launcher runs the registry from `agent-registry/` and Chris from
`chat-system/conversation-agent/`, each with its own environment, and the backend from
`backend/`, so both forms use the same two local databases. It starts each service in a separate Windows console:

| Service | Local address | Purpose |
|---|---|---|
| Frontend | http://127.0.0.1:5173 | Chat interface |
| Backend | http://127.0.0.1:8010/docs | Chat API and sign-in |
| Chris | http://127.0.0.1:8000/chris/a2a/.well-known/agent-card.json | Standalone orchestrator agent card |
| Registry | http://127.0.0.1:8001/ready | Expert-selection agent and registry management (`/registry/*`); this address is its readiness check |

Open **http://127.0.0.1:5173** to use the app. Keep the launcher terminal open and
press **Ctrl+C there** to stop all four services. If a service exits or its window
is closed, the launcher stops the others. Stop existing servers before launching
again: ports 8000, 8001, 8010, and 5173 must be available.

The launcher does not run migrations or seed the database. Restart it after code
changes; automatic reload is disabled. In a new PowerShell session, set
`DATABASE_URL` again before starting it to keep using the same database.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before making
changes. AI-generated changes remain unstaged and uncommitted for human review.
