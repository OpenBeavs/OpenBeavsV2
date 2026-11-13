# OpenBeavs v2

The OSU AI hub prototype, with a standalone Chris frontend and FastAPI backend.

- `frontend/`: Svelte chat interface and read-only registered-agent directory.
- `backend/`: chat REST API and persistence, Chris's ADK/A2A agent, and registry management.
- `docs/`: API, frontend setup, and database documentation.

Start with [local setup](#run-locally-windows-powershell), then see
[Chris's API](docs/chris.md). Chat calls Chris over A2A; Chris asks the standalone
registry to select an expert. By default Chris answers with Gemini when no expert
matches or the registry fails. Set `CHRIS_SELECTION_ONLY=true` to diagnose registry outcomes
without fallback; failures remain in service logs. No selected expert is invoked yet. Verified SSO and
service-to-service authentication remain future work.

For Agent Registry behavior, local setup, and testing, see [Agent Registry documentation](docs/registry.md).

## Run locally (Windows PowerShell)

Use Python 3.12 and Node.js 22 or later. For first-time dependency setup, run from
the repository root:

```powershell
cd .\backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -r requirements-dev.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
cd ..\frontend
npm install
cd ..
```

Edit the ignored `backend/.env` privately. Configure `CHRIS_MODEL` and
`GEMINI_API_KEY` for Chris, and `REGISTRY_MODEL` and `REGISTRY_GEMINI_API_KEY`
for registry selection. Set `REGISTRY_DEV_AUTH=true` and `REGISTRY_A2A_AUTH=dev`
only for local development. For local registry admin actions, set
`REGISTRY_ADMIN_EMAILS` to your chosen development identity. Never commit keys.
Virtual environment activation is not required for the commands below.

### 1. Create or update the local database

Open PowerShell in the repository root (`OpenBeavsV2`), then run:

```powershell
cd .\backend
$env:DATABASE_URL = 'sqlite:///./openbeavs.db'
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Wait for the command to finish successfully, then seed the standard registered agents:

```powershell
.\.venv\Scripts\python.exe -m app.db.seed_agents
```

This creates or updates `backend/openbeavs.db`. SQLite does not require a separate
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

The launcher runs Python services from `backend/`, so both forms use the same local
database. It starts each service in a separate Windows console:

| Service | Local address | Purpose |
|---|---|---|
| Frontend | http://127.0.0.1:5173 | Chat interface |
| Backend | http://127.0.0.1:8010/docs | Chat API, persistence, and registry management |
| Chris | http://127.0.0.1:8000/chris/a2a/.well-known/agent-card.json | Standalone orchestrator agent card |
| Registry agent | http://127.0.0.1:8001/ready | Expert-selection service readiness |

Open **http://127.0.0.1:5173** to use the app. Keep the launcher terminal open and
press **Ctrl+C there** to stop all four services. If a service exits or its window
is closed, the launcher stops the others. Stop existing servers before launching
again: ports 8000, 8001, 8010, and 5173 must be available.

The launcher does not run migrations or seed the database. Restart it after code
changes; automatic reload is disabled. In a new PowerShell session, set
`DATABASE_URL` again before starting it to keep using the same database.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before making
changes. AI-generated changes remain unstaged and uncommitted for human review.
