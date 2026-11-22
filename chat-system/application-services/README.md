# Application Services

The Chat System's conventional server code, with no LLM. Whatever must come out exactly right on every request lives here.

- **Turn handling.** For each turn: bound the history the browser sends, hand the message and the history to the Conversation Agent, and return the reply with the expert that answered it. Every channel (website, Teams, voice) passes through this one path.
- **Sign-in and sessions.** OSU single sign-on through Microsoft Entra ID. Application Services verifies the ID token Microsoft returns, accepts only Oregon State accounts, creates or updates the person's user record, and issues a signed session token, which the browser presents as a bearer token or a cookie. A second Microsoft sign-in with Duo multi-factor authentication raises the session to the privileged tier for 30 minutes. The session is the only source of who is asking: identity claimed in a request body is ignored. A development login (`AUTH_BYPASS_DEV=true`) stands in for Microsoft in local testing.
- **Later: settings.**
- **Later: conversation storage.** Loads, renames, and deletes conversations with no call to the Conversation Agent. Turn handling then stores each message and reply with its source, and loads the history from storage in place of the browser's copy.

Its tables live in the `chat_system` schema, created by `migrations/`.

Moves here from the dev branch: `backend/app/chat/`, `backend/app/main.py`, `backend/app/auth/`, the user, chat, message, and ticket models, its own copy of `config.py`, `db/`, and `history.py`, its migrations and tests, and the chat API's documentation, which follows.

It is its own Python package, `application_services`, in this folder, with its own environment, lock file, database, and migrations. Its tests run in that environment, and one of them checks that neither the Conversation Agent nor the Agent Registry can be imported there. The service is `application_services.main:app`, on port 8010 under the launcher.

## Frontend API

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Returns `{"status":"ok","app":"OpenBeavs v2"}`; does not check dependencies. |
| POST | `/chat/message` | Bound client history and call Chris over A2A without saving transcripts. |

The former `/chris/message` path has been replaced by `/chat/message`; no
compatibility alias is registered. The agent directory (`/chat/agents`, earlier
`/chris/agents`) has been removed: the chat API reads no registry data, and listing
registered agents is the registry's own API (`GET /registry/agents`).

### `POST /chat/message`

```json
{
  "message": "What majors does OSU offer?",
  "history": [{"role":"user","content":"Earlier question"}],
  "source_domain": "library.oregonstate.edu"
}
```

A response has this shape:

```json
{
  "response": "The answer is 42.",
  "chat_id": null,
  "routed_to": "math-expert",
  "agent_name": "Math Expert",
  "routing_confidence": null,
  "routing_reason": null,
  "routing": {
    "status": "selected",
    "agent": {"id": "math-expert", "name": "Math Expert", "description": "..."},
    "confidence": null,
    "reason": null
  }
}
```

`routing` retains successful expert metadata with `status: "selected"`.
The schema accepts legacy `no_match` replies from older Chris instances. Endpoints are never sent to the
browser. There is no error field. The UI renders `response` in a normal bubble and
shows “Answered by” with `agent_name` for expert replies. `routing` is null for Gemini answers. The older
flat fields mirror a selected result and are null otherwise. `chat_id` is always
null for compatibility. The public endpoint is stateless: history comes only from
the request, bounded before forwarding to Chris. Omit the current message from
`history`, because it is supplied separately. Legacy `chat_id`, `guest_session_id`
and `user_id` request fields are ignored, including IDs belonging to real users.
No conversation history, routing metadata or guest identifier is saved to the DB.

Errors: 400 for blank message text, 422 for invalid request bodies, 500 for
chat-to-Chris configuration errors, and 503 when Chris cannot produce a completed
A2A reply. Failed turns are not added to the browser's successful history.

The database owner handles deletion of existing guest chats and their messages
separately. The former `DELETE /chat/chats/expired` endpoint is removed.
Account-backed chat storage is not implemented.

### Sign-in routes

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/auth/authorize` | Returns the Microsoft sign-in URL and a state token, and sets the state cookie. |
| GET | `/auth/login` | Redirects to Microsoft's sign-in page; 503 when Microsoft sign-in is not configured. |
| GET | `/auth/callback`, `/oauth/microsoft/callback` | Microsoft's redirect: checks the state, verifies the ID token, records the user, and returns a page that hands the session token to the opener window. |
| GET | `/auth/me` | The signed-in person's profile and tier; 401 without a session. |
| POST | `/auth/step-up/initiate` | Starts the Duo step-up sign-in; 401 without a session. |
| GET | `/auth/step-up/callback` | Microsoft's redirect after step-up; issues a privileged session token for 30 minutes. |
| POST | `/auth/dev/login`, `/auth/dev/elevate` | Development login and elevation; 403 unless `AUTH_BYPASS_DEV=true`. |

The Microsoft settings (`MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`,
`MICROSOFT_CLIENT_TENANT_ID`, `MICROSOFT_REDIRECT_URI`), `AUTH_SECRET_KEY`, and
`FRONTEND_ORIGIN` are read from the environment or the `.env` at the repository root.

## Layout

```text
application_services/main.py          the FastAPI app: routers, CORS, /health
application_services/chat/router.py   frontend REST routes
application_services/chat/schemas.py  frontend request/response models
application_services/chat/service.py  transient history, response assembly
application_services/chat/a2a_client.py  SDK client adapter that calls Chris
application_services/auth/            sign-in, session tokens, and route guards
application_services/models/          users, chats, messages, tickets
application_services/db/              engine, sessions, and init_db
application_services/config.py        the settings it reads, from the environment or .env
application_services/history.py       the bound on the question and the history it sends Chris
migrations/                           the chat_system schema's migrations
tests/                                its tests, run in this folder's environment
```

## Database

The chat system's tables, and only those, are created by its own migrations in
`migrations/`. Run them from this folder with `DATABASE_URL` set:
`uv run alembic upgrade head`. Under PostgreSQL, connect as the `chat_system` login from
`shared-resources/postgres/owners.sql`; its `search_path` puts the tables, and Alembic's
`alembic_version` table, in the `chat_system` schema.

The first revision, `34fddc6e996d`, creates `users`, `chats`, `messages`, and
`tickets`. `chats.agent_id` holds the id the Agent Registry gave an agent, as plain
text with no foreign key, because the agents table belongs to the registry.

`DATABASE_URL` selects the database. The default, `sqlite:///./openbeavs.db`, is a file
in the folder the service starts in: `chat-system/application-services/openbeavs.db`
locally.

### A database built by the earlier, shared migrations

Until the Chat System had a package of its own, its tables were created by the shared
migrations in `backend/alembic/`, which also created the registry's `agents` table and
kept one `alembic_version` row for both. At that history's head, `e6b2c4a9f815`, the
four tables are exactly the ones `34fddc6e996d` creates. Such a database adopts this
history without changing a row:

1. Take a backup (on Cloud SQL, a backup of the instance).
2. Check read-only that `SELECT version_num FROM alembic_version;` returns
   `e6b2c4a9f815`. If it returns an earlier revision, bring it to that head with the
   shared migrations, which this tree no longer holds. Find the commit that removed
   them with `git log -1 --format=%H --diff-filter=D -- backend/alembic.ini`, check out
   its parent in a separate folder (`git worktree add <folder> <commit>^`), and from
   that checkout's `backend/`, with `DATABASE_URL` pointing at the database, run
   `uv sync --locked` and `uv run alembic upgrade head`.
3. From `chat-system/application-services/`, with the same `DATABASE_URL`, record this
   history's revision: `uv run alembic stamp --purge 34fddc6e996d`. `--purge` replaces
   the old history's version row, which this history does not know. Do this only where
   the database's `alembic_version` table belongs to the chat system alone: a database
   (or, under PostgreSQL, a schema) that the registry's migrations do not use. The
   registry adopts its own copy (see the [Agent Registry's
   README](../../agent-registry/README.md#a-database-built-by-the-earlier-shared-migrations)).
4. Remove the registry's table from the chat system's copy: `DROP TABLE agents;`. No
   chat table refers to it.
5. Verify: `uv run alembic current` prints `34fddc6e996d (head)`, `uv run alembic check`
   reports no new upgrade operations, and `SELECT count(*) FROM users;` (and the same
   for `chats`, `messages`, and `tickets`) returns what it did before.

Locally, a `backend/openbeavs.db` built before the move holds both owners' tables in one
file. Nothing reads it any longer. Application Services stores no conversations, so that
file holds at most the user records sign-in created, and a fresh database (below) is the
simple course. To keep its rows, copy it once for each owner and adopt each copy: from
the repository root, `cp backend/openbeavs.db chat-system/application-services/openbeavs.db`,
then steps 2 to 5 from this folder with `DATABASE_URL='sqlite:///./openbeavs.db'`; and
`cp backend/openbeavs.db agent-registry/openbeavs.db`, then the registry's steps. Then
delete `backend/openbeavs.db`.

## Run and test locally

Use the root README ([macOS](../../README.md#run-locally-macos) or
[Windows](../../README.md#run-locally-windows-powershell)) for dependencies, private
configuration, and launching all four services. Application Services has its own
environment and its own database. Set them up from this folder:

```zsh
uv sync --locked --python 3.12
export DATABASE_URL='sqlite:///./openbeavs.db'
uv run alembic upgrade head
```

On Windows:

```powershell
py -3.12 -m venv .venv
# --group needs pip 25.1 or later.
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e . --group dev
$env:DATABASE_URL = 'sqlite:///./openbeavs.db'
.\.venv\Scripts\python.exe -m alembic upgrade head
```

This creates `chat-system/application-services/openbeavs.db`. To start only
Application Services, run from this folder after database setup:

```zsh
uv run uvicorn application_services.main:app --host 127.0.0.1 --port 8010
```

It answers chat only when Chris and the registry are running too; the launcher starts
all four. Its API documentation is at `http://127.0.0.1:8010/docs`.

From this folder, in a separate terminal so test settings do not affect servers:

```zsh
uv sync --locked
PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run ruff check .
PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest
```

The tests cover the chat API's stateless turn handling, its A2A client and routing
validation, sign-in, the models, and the migrations, with no Gemini key. To run them
against PostgreSQL, set `TEST_CHAT_SYSTEM_DATABASE_URL` as
[the shared PostgreSQL server](../../shared-resources/postgres/README.md#test-against-it)
describes. The tests that run Application Services together with Chris and the
registry are in `tests/end-to-end/` at the repository root.
