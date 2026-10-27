# Chris (prototype)

Chris answers messages through Gemini and can pick an agent. Routing queries active agents from the database (or a mock list for offline testing) and persists conversation sessions into the database.

## API

### `GET /health`
Returns service status for Cloud Run liveness probes and local monitoring:
```json
{
  "status": "ok",
  "app": "OpenBeavs v2"
}
```

### `GET /chris/agents`
Returns the active agents Chris can route to: agents in the `agents` table whose registry status is `approved` or `provisional` (pending and revoked agents are never listed):
```json
[
  {
    "id": "8f695b47-27a7-4ce7-9932-975fc618ba1d",
    "name": "osu_rag_agent",
    "description": "An Oregon State University expert agent...",
    "endpoint_url": "https://osu-rag-agent-716080272371.us-west1.run.app/a2a/osu_rag_agent/",
    "card_url": "https://osu-rag-agent-716080272371.us-west1.run.app/a2a/osu_rag_agent",
    "trust_tier": "public",
    "required_role": null,
    "skills": [...],
    "capabilities": {"streaming": false},
    "is_featured": true
  }
]
```

### `POST /chris/message`

```json
{
  "message": "What majors does OSU offer?",
  "history": [{ "role": "user", "content": "..." }],
  "chat_id": "optional-uuid",
  "user_id": null,
  "guest_session_id": "server-issued-token-for-continuation",
  "source_domain": "library.oregonstate.edu"
}
```

Returns:
```json
{
  "response": "...",
  "chat_id": "uuid-of-session",
  "guest_session_id": "server-issued-token-for-guests",
  "routed_to": "8f695b47-27a7-4ce7-9932-975fc618ba1d",
  "agent_name": "osu_rag_agent",
  "routing_confidence": 0.94,
  "routing_reason": "Matches OSU academics and degree information"
}
```

- `chat_id`: UUID of the persisted chat session in the database.
- `routed_to` and `agent_name`: set when Chris picked an installed agent.
- `routing_*` fields show the model's decision and confidence.
- Start a guest conversation with just `message` (and optionally `history` and `source_domain`).
  Keep the returned `chat_id` and `guest_session_id`; send both to continue it.
  Treat the token as a bearer credential: do not log it or share it. Only its SHA-256 digest is stored.
- `user_id` in the body is not authentication. A supplied ID without a matching verified
  principal is rejected. SSO is not implemented; the existing `REGISTRY_DEV_AUTH`
  header mechanism can be used only in local development with a provisioned user.
- Continued chats load history from the database. Client history is accepted only
  for a new conversation. A failed ownership/history lookup never falls back to client history.
- Legacy guest sessions without server-issued credentials cannot be continued; start a new chat.
- Errors: 400 empty message; 403 wrong ownership/token or untrusted identity;
  404 unknown chat; 410 expired chat; 501 authentication not configured;
  500 missing model config; 503 model or required database lookup unavailable.
- If model generation succeeds but saving fails, the answer is returned with
  `chat_id=null` and `guest_session_id=null`; the client must not label it as saved.


## Config (`backend/.env`, git-ignored)

- `GEMINI_API_KEY`: Gemini API key
- `CHRIS_MODEL`: Gemini model id (e.g. `gemini-2.5-flash`)
- `CHRIS_USE_MOCK_AGENTS`: set to `true` to force routing against hardcoded mock agents (testing only)
- `DATABASE_URL`: Database connection string (defaults to `sqlite:///./openbeavs.db` in local dev; points to Google Cloud SQL PostgreSQL `openbeavs_v2` in production).

## Layout

```
backend/app/main.py             mounts routers
backend/app/config.py           reads env vars (including DATABASE_URL)
backend/app/db/                 SQLAlchemy 2.0 Base, engine, and get_db dependency
backend/app/models/             declarative models: Agent, User, Chat, Message, Ticket
backend/app/chris/router.py     HTTP route (queries DB agents, records turns)
backend/app/chris/llm.py        Gemini Interactions API call; provider-specific file
backend/app/chris/agent_selection.py  validated agent choice
backend/app/chris/agents.py     Agent type and explicitly enabled mock list
backend/app/chris/sessions.py   Ownership, guest credentials, ordered persistence and cleanup
backend/app/chris/prompts.py    direct-answer system prompt
backend/alembic/                database migrations
```

## Agent Routing

By default, Chris queries the active agents in the `agents` table whose registry status is `approved` or `provisional` (see `docs/registry.md`). Only public agents with no required role are eligible until caller authorization is implemented.
`CHRIS_USE_MOCK_AGENTS=true` explicitly enables `MOCK_AGENTS` for tests. An empty
catalog or failed agent lookup never enables mocks; Chris answers directly.
Mock candidate IDs are recorded only as metadata, never as nonexistent foreign keys.

If an agent is chosen, the reply currently acknowledges the routing; actual A2A HTTP client execution will be wired next. Low confidence (below 0.7) or no match falls back to a direct answer.

## Data storage & Privacy

- Requests set `store: false`, so Gemini does not retain interactions on Google's servers.
- Conversations are recorded in the local or Cloud SQL database:
  - `chats`: Stores session metadata, `source_domain` (for embedded iframe context), and an `expires_at` TTL for unauthenticated guest sessions (2 hours).
  - `messages`: Stores individual turns linked to `chat_id` with cascading deletion upon session purge.

## Run

```bash
cd backend
python -m uvicorn app.main:app --reload --env-file .env
```

Docs at http://localhost:8000/docs.

## Migrations & Seeding

```bash
# Apply database migrations
alembic upgrade head

# Seed initial agents (osu_rag_agent, Hello World, Chris)
python -m app.db.seed_agents
```

## Not migrated yet

Real A2A HTTP client dispatch, SSO token claim verification middleware, step-up MFA modals.


## Maintenance and discovery

`DELETE /chris/chats/expired` requires the existing `require_admin` dependency.
With production authentication unimplemented it fails closed; development headers
are usable only with explicit local dev auth. A scheduler is not installed by this
change. Guest continuation rejects expiry immediately, even before cleanup runs.
Cleanup deletes expired guest chats and their messages.

`GET /chris/.well-known/agent.json` returns 501 until Chris implements an actual A2A
transport. `/chris/message` is still a prototype JSON endpoint, not JSON-RPC
`message/send`; it must not be advertised as a working A2A transport. New Chris
seed rows have `card_url=NULL`; insert-only seeds do not rewrite old records.

## Message order and attribution

Messages have a unique `(chat_id, sequence)` position. Appends allocate positions
under a PostgreSQL chat-row lock; the unique constraint also rejects conflicting
SQLite writes instead of silently corrupting order. A failed append returns no
saved chat ID. Timestamps remain epoch **seconds**, consistent with existing data.
Concurrent model calls may use the same earlier history; sequence describes save
order, not serialized model execution. Clients should send one turn at a time.

`messages.agent_id` is reserved for the expert that actually authored a response.
It stays NULL for user turns, Chris responses, and unknown legacy authors. The
current "would route" message is authored by Chris, so it stays NULL too; the
chosen candidate is in `meta.selected_agent_id`. Actual A2A dispatch is not added.

Revision `b82f6d1a390c` follows the registry revision and backfills sequence by
`created_at, id`. Legacy timestamp ties get a deterministic order; their original
order cannot be recovered. It preserves IDs, contents, chat references, and existing second-based timestamps.
Modern millisecond timestamps written by Dean's interim version are normalized to
seconds after ordering; downgrade does not restore their old units.

`python -m app.db.init_db` now runs Alembic to head before insert-only seeding.
The standalone create-tables SQL is reference-only. Existing databases without an
Alembic version require verified schema baselining first; do not stamp blindly.
