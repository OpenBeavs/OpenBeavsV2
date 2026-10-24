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
  "user_id": "optional-onid-or-null",
  "guest_session_id": "optional-guest-uuid",
  "source_domain": "library.oregonstate.edu"
}
```

Returns:
```json
{
  "response": "...",
  "chat_id": "uuid-of-session",
  "routed_to": "8f695b47-27a7-4ce7-9932-975fc618ba1d",
  "agent_name": "osu_rag_agent",
  "routing_confidence": 0.94,
  "routing_reason": "Matches OSU academics and degree information"
}
```

- `chat_id`: UUID of the persisted chat session in the database.
- `routed_to` and `agent_name`: set when Chris picked an installed agent.
- `routing_*` fields show the model's decision and confidence.
- Errors: 400 empty message, 500 missing config, 503 model call failed.


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
backend/app/chris/agents.py     Agent type and mock agent fallback list
backend/app/chris/prompts.py    direct-answer system prompt
backend/alembic/                database migrations
```

## Agent Routing

By default, Chris queries the active agents in the `agents` table whose registry status is `approved` or `provisional` (see `docs/registry.md`). If `CHRIS_USE_MOCK_AGENTS=true` is set, or if the table has no rows at all (a brand-new database), it falls back to `MOCK_AGENTS` (Honors College, Engineering Advisor, Writing Center, Library).

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
