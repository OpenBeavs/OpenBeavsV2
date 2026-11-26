# OpenBeavs v2

OpenBeavs is Oregon State University's federation of expert agents. A person asks a question in the OpenBeavs Chat System, which asks the Agent Registry which expert fits, carries the question to that expert over A2A, and returns the expert's answer under a badge naming it. When no expert fits, Chris, the Chat System's Conversation Agent, answers from general knowledge with Gemini. Experts live in their own repositories.

## What this repository holds

| Folder | What it is |
|---|---|
| [`chat-system/`](chat-system/README.md) | The OpenBeavs Chat System, in three components |
| [`chat-system/web-ui/`](chat-system/web-ui/README.md) | The Web UI, the SvelteKit chat interface that runs in the browser |
| [`chat-system/application-services/`](chat-system/application-services/README.md) | Application Services: the chat API, turn handling, and Microsoft Entra ID sign-in, with its own database and migrations |
| [`chat-system/conversation-agent/`](chat-system/conversation-agent/README.md) | The Conversation Agent, called Chris in the code: an ADK agent served over A2A, with no database |
| [`agent-registry/`](agent-registry/README.md) | The Agent Registry, a separate system: it selects an expert over A2A and serves its own admin API, with its own database and migrations |
| [`shared-resources/postgres/`](shared-resources/postgres/README.md) | The SQL that gives each owner of data (the Chat System and the Registry) its own schema and login on one PostgreSQL server |
| [`tests/end-to-end/`](tests/end-to-end/README.md) | The tests that run more than one package together, and the scripted-model stack the browser pipeline test starts |
| `docs/` | Design, requirements, risks, database documentation, and the RFCs in `docs/RFCs/` |

Each Python folder (`agent-registry/`, `chat-system/application-services/`, `chat-system/conversation-agent/`, `tests/end-to-end/`) is its own uv project, with its own `pyproject.toml`, `uv.lock`, and environment. A package cannot import another package's code, and a test in each one checks this. Only `tests/end-to-end/` installs all three packages together.

Each service runs as its own process. The Web UI calls Application Services, which calls the Conversation Agent over A2A; the Conversation Agent asks the Registry over A2A which expert fits, then calls that expert.

## Prerequisites

These steps are for macOS; [Windows](#windows) lists the differences.

- **Homebrew**, from [brew.sh](https://brew.sh). It installs Apple's command line tools, which provide `git` and `make`.
- **uv**: `brew install uv`. Each package's `.python-version` asks for Python 3.12, and uv downloads it when the machine lacks it.
- **Node.js 22 or later**: `brew install node`.
- **Docker Desktop**, only for the tests against PostgreSQL 16.
- **A Gemini API key**, only for live answers. Every test runs without one.

## Install

```zsh
git clone https://github.com/OpenBeavs/OpenBeavsV2.git
cd OpenBeavsV2
(cd agent-registry && uv sync --locked)
(cd chat-system/conversation-agent && uv sync --locked)
(cd chat-system/application-services && uv sync --locked)
(cd tests/end-to-end && uv sync --locked)
(cd chat-system/web-ui && npm ci && npx playwright install chromium)
```

Every later command in this README runs from the repository root, `OpenBeavsV2/`. `npx playwright install chromium` downloads the browser the Web UI's browser tests and the pipeline test drive; `npm ci` installs Playwright without it.

## Settings

Every service reads one settings file, `.env` at the repository root. Create it from `.env.example`:

```zsh
[ -f backend/.env ] && [ ! -f .env ] && mv backend/.env .env
[ -f .env ] || cp .env.example .env
```

The first line matters only in a clone that ran the earlier layout, which kept its settings in `backend/.env`. Git ignores that file and so leaves it in place, but no service reads it now; the line moves it to the root. In a fresh clone it does nothing. If an earlier copy already created a root `.env` with blank keys beside `backend/.env`, replace it: `mv backend/.env .env`. Keep only the root `.env`: each service searches upward from the folder holding its code and reads the first `.env` it finds, so a `.env` in any folder on that path would be read in place of the root's. One in `chat-system/`, for instance, would replace it for Application Services and the Conversation Agent, while the Registry went on reading the root's.

The launchers, and the `make` targets run from one shell, give every service the same `DATABASE_URL`, so in `.env` leave it out or set it to `sqlite:///./openbeavs.db`, which each service resolves inside its own folder. Check that line in a `.env` brought from the earlier layout. Another relative name sends the launchers to files that the database commands below never create or seed, because those commands set `sqlite:///./openbeavs.db` themselves; an absolute path or a PostgreSQL address puts both owners in one database, where the second owner's migrations fail on the first owner's revision. To give each owner an address of its own, follow [Databases](#databases).

Then set these privately in `.env`; never commit it, and never paste a key into a command or a chat with an AI tool:

- `GEMINI_API_KEY`: the Conversation Agent's Gemini key, and the Registry's unless `REGISTRY_GEMINI_API_KEY` is set. Set it even when `REGISTRY_GEMINI_API_KEY` is set: the Conversation Agent reads only `GEMINI_API_KEY`, so without it the Registry still selects experts, and every question no expert covers fails.
- `REGISTRY_MODEL`: the Gemini model the Registry uses to choose an expert.
- `CHRIS_MODEL`: the Gemini model the Conversation Agent answers with when no expert fits.

The services start without these three, but a chat gets no answer until all three are set. Every other line can stay as `.env.example` has it: it runs the Registry without caller authentication (`REGISTRY_A2A_AUTH=dev`), which works only on this machine, enables the development login (`AUTH_BYPASS_DEV=true`), and leaves the Registry's admin API answering 501 (`REGISTRY_DEV_AUTH=false`) until you turn it on as [Agent Registry admin API](#agent-registry-admin-api) describes. Microsoft sign-in needs the `MICROSOFT_` settings of an app registered in Entra ID; without them `/auth/login` answers 503.

## Databases

The Registry and Application Services each keep their own database. Locally each is a SQLite file in its own folder, created by its own migrations: `agent-registry/openbeavs.db` and `chat-system/application-services/openbeavs.db`. The Conversation Agent has none. Create both, and seed the Registry with the default experts:

```zsh
(cd agent-registry && export DATABASE_URL='sqlite:///./openbeavs.db' && uv run alembic upgrade head && uv run python -m agent_registry.database.seed_agents)
(cd chat-system/application-services && export DATABASE_URL='sqlite:///./openbeavs.db' && uv run alembic upgrade head)
```

Run the migrations again whenever a pull brings new ones. Rerunning the seed adds any missing default agent and leaves existing ones unchanged. `make migrate` and `make seed` run the same commands with the `DATABASE_URL` in your shell or `.env`.

To give each owner an address of its own, for instance to run the stack on a local PostgreSQL server prepared as [Test against it](shared-resources/postgres/README.md#test-against-it) describes, start each service in its own terminal, with that owner's `DATABASE_URL` in the terminal's environment, and run its migrations there the same way:

```zsh
# Terminal 1: the Agent Registry
export DATABASE_URL='postgresql+psycopg2://registry:local-registry@127.0.0.1:5432/openbeavs'
(cd agent-registry && uv run alembic upgrade head && uv run python -m agent_registry.database.seed_agents)
make dev-registry

# Terminal 2: Application Services
export DATABASE_URL='postgresql+psycopg2://chat_system:local-chat-system@127.0.0.1:5432/openbeavs'
(cd chat-system/application-services && uv run alembic upgrade head)
make dev-back
```

Start the other two services with `make dev-chris` and `make dev-front`, each in a terminal of its own.

**A `backend/openbeavs.db` left from before the reorganization** holds both owners' tables in one file, and nothing reads it now. The fresh databases above are the simple course. To keep its rows, each owner adopts a copy by the steps in [Application Services' README](chat-system/application-services/README.md#a-database-built-by-the-earlier-shared-migrations) and the [Agent Registry's README](agent-registry/README.md#a-database-built-by-the-earlier-shared-migrations). A PostgreSQL database built the same way moves into the owners' schemas by the steps in [`shared-resources/postgres/README.md`](shared-resources/postgres/README.md#a-database-built-by-the-earlier-shared-migrations).

## Start

```zsh
bash start-dev-mac.sh
```

The script runs the launcher, `start-dev.py`, with Application Services' Python and each service's database set to its SQLite file. The launcher starts all four services in this terminal, each Python service from its own folder and environment:

| Service | Address |
|---|---|
| Agent Registry | `http://127.0.0.1:8001` (A2A selection at `/a2a/registry/`, the admin API at `/registry/agents`, which answers 501 until [development authentication](#agent-registry-admin-api) is on, readiness at `/ready`) |
| Conversation Agent | `http://127.0.0.1:8000/chris/a2a/` |
| Application Services | `http://127.0.0.1:8010` (API documentation at `/docs`) |
| Web UI | port 8080 when `MICROSOFT_REDIRECT_URI` names it, as `.env.example` does; otherwise 5173. `FRONTEND_PORT` overrides both |

Open [http://localhost:8080](http://localhost:8080). Use `localhost` rather than `127.0.0.1`: Microsoft returns the browser to the origin `MICROSOFT_REDIRECT_URI` names, sign-in works only when the page and its cookie are on that origin, and a browser treats the two names as different origins. The status button at the top of the page reads "Backend connected" once Application Services answers.

Press **Ctrl+C** in the launcher's terminal to stop all four. If any service exits, the launcher stops the others. It does not reload on code changes, so restart it after an edit.

To run the launcher directly, with the `DATABASE_URL` in your shell or `.env`:

```zsh
uv run --no-project --python 3.12 python start-dev.py
```

**"Port 8010 is unavailable. Stop its server first."** The launcher checks every port before it starts anything. For up to about a minute after a stack stops, macOS still holds its ports, and the launcher reports one of them unavailable. Wait, and start again. If the message persists, a server is still running: `make stop` stops whatever listens on the stack's ports.

The `Makefile` gives the same commands short names:

| Target | What it does |
|---|---|
| `make run`, `make dev` | Start all four services with `start-dev.py` |
| `make stop`, `make down` | Stop whatever listens on ports 8000, 8001, 8010, 5173, and 8080 |
| `make dev-registry` | Start only the Agent Registry, with the launcher's settings |
| `make dev-chris` | Start only the Conversation Agent |
| `make dev-back` | Start only Application Services, reloading on edits |
| `make dev-front` | Start only the Web UI |
| `make migrate` | Run both owners' migrations |
| `make seed` | Seed the Registry's default agents |
| `make lint` | Run ruff in every Python folder, then the Web UI's ESLint and type checks |
| `make test` | Run every Python suite, then the Web UI's unit tests, with the settings in `.env` (see [Tests](#tests)) |
| `make help` | List the targets |

Each `make dev-*` target runs in its own terminal, so run each of the four in a terminal of its own to assemble the stack by hand.

### Agent Registry admin API

The Registry's admin API, at `http://127.0.0.1:8001/registry/agents`, answers every request with 501 until development authentication is on, because the Registry has no verified sign-in of its own yet. Two settings turn it on:

- `REGISTRY_DEV_AUTH`: `true` (or `1` or `yes`) makes the Registry take the caller's identity from each request's `X-User-Id` and `X-User-Email` headers, and answer 401 when either is missing. Any other value leaves the API answering 501.
- `REGISTRY_ADMIN_EMAILS`: a comma-separated list of the email addresses that count as admins. Any caller with both headers may submit an agent and list the agents it may see; only an admin may review one, and anyone else gets 403.

The Registry believes whatever the headers say, so anyone who can reach it can claim any identity. Use development authentication only on your own machine: the Registry refuses to start with it on Cloud Run or with a `DATABASE_URL` that names another machine. Set the two settings in the command that starts the Registry, rather than in `.env`, so that they never travel into a deployment with a copied `.env`. With no stack running, start the Registry alone:

```zsh
REGISTRY_DEV_AUTH=true REGISTRY_ADMIN_EMAILS=admin@example.test make dev-registry
```

In another terminal, list the registered agents as the admin:

```zsh
curl -H 'X-User-Id: admin' -H 'X-User-Email: admin@example.test' http://127.0.0.1:8001/registry/agents
```

It answers 200 with the seeded agents; the same request without the headers answers 401. To run the whole stack with the API on, put the same two settings before `bash start-dev-mac.sh`. The Agent Registry's README lists [the routes](agent-registry/README.md#endpoints) and walks through [submitting and reviewing an expert](agent-registry/README.md#submit-and-review-an-expert-agent).

## What to expect

- **The seeded OSU expert** (`osu_rag_agent`) runs on Google Cloud Run. When it has been idle it takes about 17 seconds to answer, so the first OSU question after a pause is slow.
- **The seeded "Hello World Agent"** points at a sample server that answers HTTP 404. The Registry routes a greeting such as "hello" to it, the call fails, and the Web UI shows "Chris is temporarily unavailable" instead of an answer. Ask a real question instead.
- **An expert's answer** carries a badge under it, "Answered by" and the expert's name, taken from the Registry's record. A general answer from Chris carries no badge.
- **The conversation lives in the browser for guests, and in Application Services' database for signed-in users.** Unauthenticated chat is stateless (the Web UI sends bounded history with each message, and a reload clears it). Signed-in callers persist chats and turns via `POST /chat/message` (`chat_id`) and `/chat/chats*`.
- **Sign-in.** Microsoft Entra ID single sign-on (`GET /auth/login`, `/auth/callback`) and `POST /auth/logout` are built into Application Services' API (`/auth/*`), creating a user record for each person who signs in. The Web UI has no sign-in screen yet, and guest chat works without signing in. `AUTH_BYPASS_DEV` and missing/placeholder `AUTH_SECRET_KEY` values are refused in deployments (Cloud Run or non-local databases).

## Tests

Run each package's lint and tests from its own folder, in a terminal separate from a running stack. `PYTHON_DOTENV_DISABLED=1` keeps the tests from reading your `.env`, and the in-memory database keeps them from touching your local files, as in CI:

```zsh
(cd agent-registry && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
(cd chat-system/conversation-agent && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 uv run pytest)
(cd chat-system/application-services && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
(cd tests/end-to-end && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
```

On SQLite the end-to-end suite skips the 16 grants tests, which need PostgreSQL.

`make test` runs the same Python suites, then the Web UI's unit tests, without `PYTHON_DOTENV_DISABLED=1` or the in-memory `DATABASE_URL`, so the Python tests load `.env` as the services do, and every setting in it reaches them. They build their own databases, so the local database files stay unchanged. The commands above are the ones CI runs.

The Web UI's lint and type checks, unit tests, production build, and browser tests:

```zsh
(cd chat-system/web-ui && npm run lint && npm run test && npm run build && npm run test:e2e)
```

The pipeline test starts the real Registry, Conversation Agent, and Application Services code on ports 8100 to 8102, with a scripted stand-in for Gemini, and drives the Web UI in a browser on port 5273. It starts the services with `tests/end-to-end/`'s environment, so that folder must be installed first, and it needs no key:

```zsh
(cd chat-system/web-ui && npm run test:pipeline)
```

To run the grants test, which proves that each owner's database login is refused the other owner's tables, and every suite against PostgreSQL 16 in Docker, follow [Test against it](shared-resources/postgres/README.md#test-against-it).

CI runs all of these on every push and pull request (`.github/workflows/checks.yml`): one job per Python package, a Web UI job, and an end-to-end job that runs the end-to-end suite, the grants test, and the pipeline test on PostgreSQL 16.

## Deploying to a host

A deployment runs three Python services, each from its own folder with its own environment, plus the Web UI's static files:

| Service | Folder | Entry point |
|---|---|---|
| Agent Registry | `agent-registry/` | `uvicorn agent_registry.a2a_app:create_standalone_app --factory --host 0.0.0.0 --port <port>` |
| Conversation Agent | `chat-system/conversation-agent/` | `uvicorn conversation_agent.run:create_app --factory --host 0.0.0.0 --port <port>` |
| Application Services | `chat-system/application-services/` | `uvicorn application_services.main:app --host 0.0.0.0 --port <port>` |
| Web UI | `chat-system/web-ui/` | `npm run build` writes static files to `build/` |

Each service reads its settings from its environment. Set its addresses so the services find one another:

- the Conversation Agent's `CHRIS_PUBLIC_URL`: its own public address, which its A2A card advertises;
- Application Services' `CHRIS_A2A_URL`: the Conversation Agent's address followed by `/chris/a2a/`;
- the Registry's `REGISTRY_PUBLIC_URL`: its own public origin, which must be HTTPS on Cloud Run;
- the Conversation Agent's `REGISTRY_A2A_URL`: the Registry's origin followed by `/a2a/registry`.

The Registry's own service serves its admin API, at `/registry/agents`; Application Services does not. Deploy the three services from the same commit: each validates the others' messages exactly, so a service from another commit can reject every turn.

**Databases.** Each owner connects with its own login to one PostgreSQL server. An admin login applies `shared-resources/postgres/owners.sql` once, which creates a schema and a login for each owner, and sets the logins' passwords. The Registry's `DATABASE_URL` then signs in as `registry`, and Application Services' as `chat_system`; [`shared-resources/postgres/README.md`](shared-resources/postgres/README.md) gives the commands. Each URL begins `postgresql+psycopg2://`, because the packages install the psycopg2 driver and SQLAlchemy 2.1 looks for a different driver under `postgresql://`. Run each owner's migrations from its folder, signed in as its login (`uv run alembic upgrade head`), and seed the Registry with `agent-registry/scripts/seed_agents.sql` or the Python seed. A database built by the earlier shared migrations adopts each owner's history by the steps in the [two](chat-system/application-services/README.md#a-database-built-by-the-earlier-shared-migrations) [package READMEs](agent-registry/README.md#a-database-built-by-the-earlier-shared-migrations) and [`shared-resources/postgres/README.md`](shared-resources/postgres/README.md#a-database-built-by-the-earlier-shared-migrations).

**The Web UI's host** serves the files in `build/`, falls back to `index.html` for other paths, and sends `/chat/message`, `/health`, `/auth/*`, and `/oauth/*` to Application Services before that fallback.

**What is untested on a host.** None of these services has been deployed from this layout, and the repository holds no container definition. Two gaps block expert selection in a deployment today. The Conversation Agent attaches no credential when it calls the Registry, so a Registry in `google` mode (`REGISTRY_A2A_AUTH`), which verifies Google ID tokens, refuses every selection. The Registry refuses `dev` mode, which accepts unauthenticated calls, on Cloud Run or with a database on another machine. In either case every question gets Chris's general answer. The Registry's admin API answers 501 in a deployment, as it does locally until [development authentication](#agent-registry-admin-api) is on, and the Registry refuses to start with development authentication there. It has no verified sign-in of its own, so agents in a deployment come only from the seed. Cloud Run, Cloud SQL, IAM, and Microsoft sign-in against a deployed redirect address have not been verified.

## Windows

Use PowerShell for the commands below. Run them from the repository root, in order, and stop if a command fails. Homebrew, Bash, and Make are not required on Windows.

### Prerequisites

Install Git, Node.js **22 or newer**, and uv. Docker Desktop is needed only for the PostgreSQL tests. A Gemini API key is needed only for live answers; the automated tests run without one.

Install uv using its [official Windows package](https://docs.astral.sh/uv/getting-started/installation/#winget):

```powershell
winget install --id=astral-sh.uv -e
```

Open a new PowerShell window after installation and verify the tools:

```powershell
git --version
node --version
npm.cmd --version
uv --version
```

Each Python project requests Python 3.12, and uv obtains it if needed. If you already have the repository, change to its root before continuing. For a new checkout of the restructuring branch:

```powershell
git clone --branch restructure/v2-tree --single-branch https://github.com/OpenBeavs/OpenBeavsV2.git
cd .\OpenBeavsV2
```

The branch above is the source of PR #33. After that work is merged, use the team's intended development branch instead.

### Install

```powershell
foreach ($project in @(
    'agent-registry'
    'chat-system/conversation-agent'
    'chat-system/application-services'
    'tests/end-to-end'
)) {
    uv --directory $project sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Install failed: $project" }
}

Push-Location chat-system/web-ui
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend installation failed' }
    npx.cmd playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed' }
}
finally {
    Pop-Location
}
```

Each Python project has its own `.venv`; Python packages are not installed globally. `uv run` selects the appropriate environment without activation. Frontend packages go into `chat-system/web-ui/node_modules`. The `.cmd` suffix avoids PowerShell execution-policy restrictions on npm's and npx's `.ps1` wrappers.

### Settings

Every service reads the one `.env` at the repository root. If the team supplied a configured file, place it there. Otherwise, move the earlier layout's settings if present, or copy the example without overwriting an existing file:

```powershell
if ((Test-Path -LiteralPath backend/.env) -and !(Test-Path -LiteralPath .env)) {
    Move-Item -LiteralPath backend/.env -Destination .env -ErrorAction Stop
}
if (!(Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env -ErrorAction Stop
}
```

Privately configure `GEMINI_API_KEY`, `REGISTRY_MODEL`, and `CHRIS_MODEL` before testing live answers. Never commit `.env`, paste its contents into chat, or create additional `.env` files in component folders. For this local SQLite setup, leave `DATABASE_URL` absent or set it to `sqlite:///./openbeavs.db`.

The example enables local development authentication bypass (`AUTH_BYPASS_DEV=true`) and local unauthenticated Registry selection (`REGISTRY_A2A_AUTH=dev`). These settings are for local development. Microsoft Entra sign-in requires the separate configuration described under [Settings](#settings).

### Databases

In a fresh PowerShell window at the repository root, create the two local SQLite databases and seed the Registry. These commands explicitly select SQLite and disable `.env` loading during initialization:

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
$env:DATABASE_URL = 'sqlite:///./openbeavs.db'

try {
    uv --directory agent-registry run alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Registry migration failed' }
    uv --directory agent-registry run python -m agent_registry.database.seed_agents
    if ($LASTEXITCODE -ne 0) { throw 'Registry seeding failed' }
    uv --directory chat-system/application-services run alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Application Services migration failed' }
}
finally {
    Remove-Item Env:PYTHON_DOTENV_DISABLED -ErrorAction SilentlyContinue
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
}
```

This creates `agent-registry/openbeavs.db` and `chat-system/application-services/openbeavs.db`. The Conversation Agent has no database. Rerun migrations after receiving new migrations; rerunning the seed leaves existing default agents unchanged. Close this setup window afterward so its temporary environment changes cannot affect later work.

### Start and stop

Open PowerShell at the repository root and run:

```powershell
.\chat-system\application-services\.venv\Scripts\python.exe .\start-dev.py
```

The launcher opens each service in its own console. Keep the launcher terminal open and press **Ctrl+C in that terminal** to stop all four services. Restart after code changes. If a required port is occupied, stop the existing stack before launching another copy.

Open [http://localhost:8080](http://localhost:8080), or the frontend URL printed by the launcher. `FRONTEND_PORT` overrides the port in `MICROSOFT_REDIRECT_URI`; without either setting, the frontend defaults to 5173. Application Services exposes its API documentation at [http://127.0.0.1:8010/docs](http://127.0.0.1:8010/docs), and Registry readiness is at [http://127.0.0.1:8001/ready](http://127.0.0.1:8001/ready).

### Tests

Open a separate, fresh PowerShell window at the repository root. Run every Python project's lint and tests with `.env` loading disabled and an in-memory database:

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
$env:DATABASE_URL = 'sqlite:///:memory:'

try {
    foreach ($project in @(
        'agent-registry'
        'chat-system/conversation-agent'
        'chat-system/application-services'
        'tests/end-to-end'
    )) {
        uv --directory $project run ruff check .
        if ($LASTEXITCODE -ne 0) { throw "Lint failed: $project" }
        uv --directory $project run pytest
        if ($LASTEXITCODE -ne 0) { throw "Tests failed: $project" }
    }

    Push-Location chat-system/web-ui
    try {
        foreach ($task in @('lint', 'test', 'build', 'test:e2e', 'test:pipeline')) {
            npm.cmd run $task
            if ($LASTEXITCODE -ne 0) { throw "Frontend check failed: $task" }
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Remove-Item Env:PYTHON_DOTENV_DISABLED -ErrorAction SilentlyContinue
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
}
```

Close the test window afterward. The pipeline test starts the real service code with scripted model and expert responses and drives the UI in Chromium. It needs the `tests/end-to-end` environment installed above, but no Gemini key.

The SQLite run skips the **16 PostgreSQL grants tests**, so it does not prove the database permission boundaries. Follow [Test against it](shared-resources/postgres/README.md#test-against-it) for the PostgreSQL setup and owner-specific connection settings; the shell examples there use macOS syntax and need PowerShell equivalents on Windows. Microsoft Entra sign-in also requires separate verification.

For a live smoke test, confirm the UI shows "Backend connected", ask a general question, ask an OSU question and check the expert attribution, then ask a follow-up that depends on the previous answer. Avoid using "hello" as the routing check: the seeded Hello World expert points to an unavailable sample endpoint. Refreshing the page clears the conversation.

At commit `bd1a6c2`, local Windows verification passed Registry 588, Conversation Agent 152, Application Services 101, end-to-end 106 (with 16 PostgreSQL grants tests skipped), Web UI unit tests 46, browser tests 7, and scripted pipeline tests 9. All Python lint and Web UI lint/type checks passed, and the production build completed with Svelte compatibility warnings. Live Gemini fallback and OSU expert requests also succeeded. PostgreSQL grants and Microsoft Entra sign-in were not verified on Windows. npm reported 19 dependency vulnerabilities in the locked dependencies; these remain unresolved.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md), which holds the instructions for AI coding agents, before making changes. AI-generated changes remain unstaged and uncommitted for human review.
