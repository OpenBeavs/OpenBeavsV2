# End-to-end tests

Tests that run more than one package together, such as a full turn from the API through the Registry to an expert. A test that exercises one component lives in that component's `tests/` folder.

Moved here from the dev branch: `backend/tests/integration/`, `backend/scripts/fake_model_stack.py`, and the tests that run two packages together. The database grants test was added here with `shared-resources/postgres/`.

This folder holds no application code. Each Python service is its own package with its
own tests: [Application Services](../../chat-system/application-services/README.md),
[Chris, the Conversation Agent](../../chat-system/conversation-agent/README.md), and
[the Agent Registry](../../agent-registry/README.md). This folder's environment installs
all three from their folders as editable packages, so the tests here can run them side
by side.

- `tests/integration/`: the real Chat, Chris, and registry pipeline in one process, with
  a fake model.
- `tests/test_*.py`: Application Services' client calling the real Chris, and the
  database grants test (`tests/test_database_grants.py`).
- `tests/databases.py`: each owner's tables, on SQLite or on PostgreSQL.
- `scripts/fake_model_stack.py`: the same pipeline on loopback ports, which the Web
  UI's `npm run test:pipeline` (in `chat-system/web-ui/`) starts with this folder's
  environment.

## Dependencies and checks

From `tests/end-to-end/`:

```zsh
uv sync --locked
PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run ruff check .
PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest
```

On Windows:

```powershell
py -3.12 -m venv .venv
# --group needs pip 25.1 or later.
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ..\..\agent-registry -e ..\..\chat-system\conversation-agent -e ..\..\chat-system\application-services --group dev
$env:PYTHON_DOTENV_DISABLED='1'
$env:DATABASE_URL='sqlite:///:memory:'
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

Run tests in a separate terminal from the servers. The suite includes the
real-implementation pipeline (Application Services, Chris and the registry) with a fake
model, the tests of Chat calling the real Chris, and `tests/test_database_grants.py`. No
Gemini key is needed.

The tests use SQLite. To run them against PostgreSQL, with the chat system and the
registry each signed in under its own login and confined to its own schema, see
[the shared PostgreSQL server](../../shared-resources/postgres/README.md#test-against-it).
The grants test runs only there.
