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
Returns active external agents whose registry status is `approved` or
`provisional`, whose trust tier is `public`, and which have no required role.
Chris itself, pending agents, and revoked agents are excluded. The frontend
displays this list as a read-only directory; listing is not execution authorization:
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
- Errors: 400 empty message, 403 denied chat access, 422 invalid request,
  500 missing config or other server failure, 503 model call failed.
- A non-null `chat_id` selects database history instead of client history. If
  persistence fails, the reply may still succeed with `chat_id: null`.
- `user_id` is currently a caller-supplied lookup, not verified SSO identity.
  The guest-only frontend omits it and uses `guest_session_id` instead.


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
backend/app/chat/router.py      frontend message, agent-list and cleanup HTTP routes
backend/app/chat/schemas.py     frontend request and response schemas
backend/app/chat/service.py     chat access checks, history, persistence and agent lookup
backend/app/chris/router.py     Chris discovery card HTTP route
backend/app/chris/service.py    direct-answer prompt composition and model invocation
backend/app/chris/llm.py        Gemini Interactions API call; provider-specific file
backend/app/chris/agent_selection.py  validated agent choice
backend/app/chris/agents.py     Agent type and mock agent fallback list
backend/app/chris/prompts.py    direct-answer system prompt
backend/alembic/                database migrations
```

Chat routes remain mounted at `/chris` to preserve the frontend API, response
schemas, status codes and discovery-card URLs. The chat service performs the
existing access checks, asks Chris's selection code to choose an eligible agent,
loads stored history for direct answers, and persists the resulting turn. Chris's
direct-answer service accepts message text, history and agent metadata; it does
not access the chat database. This separation does not introduce ADK execution
or A2A dispatch.

## Agent Routing

By default, Chris selects active public agents with no required role whose
registry status is `approved` or `provisional`, excluding Chris itself
(see [Agent Registry](registry.md)).

Only `CHRIS_USE_MOCK_AGENTS=true` selects the mock list (Honors College,
Engineering Advisor, Writing Center, Library). An empty table or failed agent
query produces an empty routing list, and Chris answers directly. Mock agents
are routing fixtures, not an offline model.

If an agent is chosen, the reply currently acknowledges the routing; actual A2A HTTP client execution will be wired next. Low confidence (below 0.7) or no match falls back to a direct answer.

## Data storage & Privacy

- Requests set `store: false`, so Gemini does not retain interactions on Google's servers.
- Conversations are recorded in the local or Cloud SQL database:
  - `chats`: Stores session metadata, `source_domain` (for embedded iframe context), and an `expires_at` TTL for unauthenticated guest sessions (2 hours).
  - `messages`: Stores individual turns linked to `chat_id` with cascading deletion upon session purge.
- `DELETE /chris/chats/expired` invokes the cleanup helper. No scheduler is
  installed by this repository; the expiry timestamp alone does not delete
  chats or reject further turns. The frontend does not call this route.
- Encryption-related columns exist, but this request path stores plaintext;
  verified SSO, guest promotion, and envelope encryption are not implemented.

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

## Frontend

See [frontend setup and integration](frontend.md). The standalone Svelte frontend
uses the existing health, directory, and message endpoints through a same-origin
development/preview proxy. The message endpoint returns ordinary JSON. The
discovery card currently advertises streaming, but streaming is not implemented.
Saved-chat list/retrieval endpoints are also not implemented.
