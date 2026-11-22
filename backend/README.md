# OpenBeavs v2 backend

The backend holds the Chat REST API (`app.main:app`), with sign-in. Chris, the
Conversation Agent, is its own package in
[`../chat-system/conversation-agent/`](../chat-system/conversation-agent/README.md), started
as its own process. The registry service, which serves both A2A selection and registry
management (`/registry/*`), is its own package in
[`../agent-registry/`](../agent-registry/README.md). The pipeline tests here and the
fake-model stack start the registry and Chris beside the chat API, so this environment
installs both from their folders as editable packages; the chat API's code imports
neither. Development uses Python 3.12 and local SQLite; Cloud SQL is not required.

Follow [the root README](../README.md#run-locally-windows-powershell) for first-time setup,
private model configuration, migrations, seeding, and the all-services launcher.
It uses ports 8010 (backend), 8000 (Chris), 8001 (registry), and 5173 (frontend).
Chris and the registry service are each started separately from `app.main:app`,
which hosts neither.

The default workflow invokes the selected expert or answers with Gemini on no match
or a registry failure (fallback requires `GEMINI_API_KEY` and `CHRIS_MODEL`).
Expert calls default to A2A 0.3 for the seeded experts; set `CHRIS_EXPERT_A2A_VERSION=1.0`
for 1.0 experts. See [dispatch configuration](../chat-system/conversation-agent/README.md#expert-dispatch). Failures are logged and return a generic
availability notice without saving failed conversation turns.
The registry uses its own `REGISTRY_MODEL` and `REGISTRY_GEMINI_API_KEY` configuration.

## Dependencies and checks

From `backend/`, use the local virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ..\agent-registry -e ..\chat-system\conversation-agent -e . -r requirements-dev.txt
$env:PYTHON_DOTENV_DISABLED='1'
$env:DATABASE_URL='sqlite:///:memory:'
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

Run tests in a separate terminal from the servers. The backend suite includes the
real-implementation pipeline (Chat, Chris and the registry) with a fake model, and the
tests of Chat calling the real Chris. Chris's own tests run from
`../chat-system/conversation-agent/`, and the registry's from `../agent-registry/`. No
Gemini key is needed for these tests.

The tests use SQLite. To run them against PostgreSQL, with the chat system and the
registry each signed in under its own login and confined to its own schema, see
[the shared PostgreSQL server](../shared-resources/postgres/README.md#test-against-it).

Alternatively `uv sync --locked` installs the runtime from `uv.lock`; install the test
tools from `requirements-dev.txt` as well. The lockfile installs the registry from
`../agent-registry/` and Chris from `../chat-system/conversation-agent/` as editable
packages. Do not copy a virtual environment from the
scratch folder.

## Inspect the local services

With the runbook's servers running:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health
Invoke-RestMethod http://127.0.0.1:8000/chris/a2a/.well-known/agent-card.json
Invoke-RestMethod http://127.0.0.1:8001/ready
```

`/health` indicates process liveness. The registry's `/ready` checks its table schema,
configuration and auth mode without making a model request. It does not verify that
Google accepts the configured model/key. Chat's API documentation is at
`http://127.0.0.1:8010/docs`.

For contracts and current limitations, see [Chris](../chat-system/conversation-agent/README.md) and
[the registry](../agent-registry/README.md). Keep credentials in the ignored `.env` at the repository root
or private process environment; do not put them in frontend configuration or Git.
