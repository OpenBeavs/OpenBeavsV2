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

The first line matters only in a clone that ran the earlier layout, which kept its settings in `backend/.env`. Git ignores that file and so leaves it in place, but no service reads it now; the line moves it to the root. In a fresh clone it does nothing. If an earlier copy already created a root `.env` with blank keys beside `backend/.env`, replace it: `mv backend/.env .env`. Keep only the root `.env`: the services find it by searching upward from their own folders, so a `.env` inside a package folder would be read in its place.

Then set these privately in `.env`; never commit it, and never paste a key into a command or a chat with an AI tool:

- `GEMINI_API_KEY`: the Conversation Agent's Gemini key, and the Registry's unless `REGISTRY_GEMINI_API_KEY` is set. Set it even when `REGISTRY_GEMINI_API_KEY` is set: the Conversation Agent reads only `GEMINI_API_KEY`, so without it the Registry still selects experts, and every question no expert covers fails.
- `REGISTRY_MODEL`: the Gemini model the Registry uses to choose an expert.
- `CHRIS_MODEL`: the Gemini model the Conversation Agent answers with when no expert fits.

The services start without these three, but a chat gets no answer until all three are set. Every other line can stay as `.env.example` has it: it runs the Registry without caller authentication (`REGISTRY_A2A_AUTH=dev`), which works only on this machine, and enables the development login (`AUTH_BYPASS_DEV=true`). Microsoft sign-in needs the `MICROSOFT_` settings of an app registered in Entra ID; without them `/auth/login` answers 503.

## Databases

The Registry and Application Services each keep their own database. Locally each is a SQLite file in its own folder, created by its own migrations: `agent-registry/openbeavs.db` and `chat-system/application-services/openbeavs.db`. The Conversation Agent has none. Create both, and seed the Registry with the default experts:

```zsh
(cd agent-registry && export DATABASE_URL='sqlite:///./openbeavs.db' && uv run alembic upgrade head && uv run python -m agent_registry.database.seed_agents)
(cd chat-system/application-services && export DATABASE_URL='sqlite:///./openbeavs.db' && uv run alembic upgrade head)
```

Run the migrations again whenever a pull brings new ones. Rerunning the seed adds any missing default agent and leaves existing ones unchanged. `make migrate` and `make seed` run the same commands with the `DATABASE_URL` in `.env`.

**A `backend/openbeavs.db` left from before the reorganization** holds both owners' tables in one file, and nothing reads it now. The fresh databases above are the simple course. To keep its rows, each owner adopts a copy by the steps in [Application Services' README](chat-system/application-services/README.md#a-database-built-by-the-earlier-shared-migrations) and the [Agent Registry's README](agent-registry/README.md#a-database-built-by-the-earlier-shared-migrations). A PostgreSQL database built the same way moves into the owners' schemas by the steps in [`shared-resources/postgres/README.md`](shared-resources/postgres/README.md#a-database-built-by-the-earlier-shared-migrations).

## Start

```zsh
bash start-dev-mac.sh
```

The script runs the launcher, `start-dev.py`, with Application Services' Python and each service's database set to its SQLite file. The launcher starts all four services in this terminal, each Python service from its own folder and environment:

| Service | Address |
|---|---|
| Agent Registry | `http://127.0.0.1:8001` (A2A selection at `/a2a/registry/`, the admin API at `/registry/agents`, readiness at `/ready`) |
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
| `make test` | Run every Python suite, then the Web UI's unit tests |
| `make help` | List the targets |

Each `make dev-*` target runs in its own terminal, so run each of the four in a terminal of its own to assemble the stack by hand.

## What to expect

- **The seeded OSU expert** (`osu_rag_agent`) runs on Google Cloud Run. When it has been idle it takes about 17 seconds to answer, so the first OSU question after a pause is slow.
- **The seeded "Hello World Agent"** points at a sample server that answers HTTP 404. The Registry routes a greeting such as "hello" to it, the call fails, and the Web UI shows "Chris is temporarily unavailable" instead of an answer. Ask a real question instead.
- **An expert's answer** carries a badge under it, "Answered by" and the expert's name, taken from the Registry's record. A general answer from Chris carries no badge.
- **The conversation lives in the browser.** Application Services stores no conversations; the Web UI sends the history with each message, and a reload clears it.
- **Sign-in.** Microsoft Entra ID single sign-on is built into Application Services' API (`/auth/*`), and it creates a user record for each person who signs in. The Web UI has no sign-in screen yet, and chat works without signing in.

## Tests

Run each package's lint and tests from its own folder, in a terminal separate from a running stack. `PYTHON_DOTENV_DISABLED=1` keeps the tests from reading your `.env`, and the in-memory database keeps them from touching your local files, as in CI:

```zsh
(cd agent-registry && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
(cd chat-system/conversation-agent && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 uv run pytest)
(cd chat-system/application-services && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
(cd tests/end-to-end && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
```

On SQLite the end-to-end suite skips the 16 grants tests, which need PostgreSQL.

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

**What is untested on a host.** None of these services has been deployed from this layout, and the repository holds no container definition. Two gaps block expert selection in a deployment today. The Conversation Agent attaches no credential when it calls the Registry, so a Registry in `google` mode (`REGISTRY_A2A_AUTH`), which verifies Google ID tokens, refuses every selection. The Registry refuses `dev` mode, which accepts unauthenticated calls, on Cloud Run or with a database on another machine. In either case every question gets Chris's general answer. The Registry's admin API also answers 501 in a deployment, because it has no verified sign-in of its own, so agents there come only from the seed. Cloud Run, Cloud SQL, IAM, and Microsoft sign-in against a deployed redirect address have not been verified.

## Windows

The launcher runs on Windows and opens each service in a console of its own. uv and Node.js behave the same in PowerShell, so run the install, database, and test commands above from each folder, with PowerShell's syntax for changing folders and setting variables (`$env:DATABASE_URL = 'sqlite:///./openbeavs.db'`). Start the stack from the repository root with `.\chat-system\application-services\.venv\Scripts\python.exe start-dev.py`. These Windows steps have not been rehearsed for this layout.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before making changes. AI-generated changes remain unstaged and uncommitted for human review.
