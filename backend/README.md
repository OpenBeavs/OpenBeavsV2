# OpenBeavs v2 end-to-end tests

This folder holds the tests that run the Chat System and the Agent Registry together,
and the fake-model stack (`scripts/fake_model_stack.py`) that the frontend's
`npm run test:pipeline` starts. It holds no application code. Each system is its own
package with its own tests:
[Application Services](../chat-system/application-services/README.md),
[Chris, the Conversation Agent](../chat-system/conversation-agent/README.md), and
[the Agent Registry](../agent-registry/README.md). This environment installs all three
from their folders as editable packages, so the tests here can run them side by side.

## Dependencies and checks

From `backend/`:

```zsh
uv sync --locked
PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run ruff check .
PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest
```

On Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ..\agent-registry -e ..\chat-system\conversation-agent -e ..\chat-system\application-services -r requirements-dev.txt
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
[the shared PostgreSQL server](../shared-resources/postgres/README.md#test-against-it).
The grants test runs only there.
