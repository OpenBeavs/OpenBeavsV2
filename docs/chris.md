# Chris (prototype)

Chris answers messages through Gemini and can pick an agent. Agents and agent calling are not migrated yet, so routing is tested with a mock list.

## API

`POST /chris/message`

```json
{ "message": "Hello", "history": [{ "role": "user", "content": "..." }] }
```

Returns `{ "response": "..." }`, plus `routed_to`, `agent_name`, `routing_confidence`, `routing_reason` (null when routing did not run or picked no agent). `history` is optional (roles: `user`, `assistant`).
Errors: 400 empty message, 500 missing config, 503 model call failed.

## Config (`backend/.env`, git-ignored)

- `GEMINI_API_KEY`: Gemini API key
- `CHRIS_MODEL`: Gemini model id (no default)
- `CHRIS_USE_MOCK_AGENTS`: set to `true` to route against the mock agents (testing only)

## Layout

```
backend/app/main.py           mounts routers
backend/app/config.py         reads env vars
backend/app/chris/router.py   HTTP route
backend/app/chris/llm.py      Gemini Interactions API call; the only provider-specific file
backend/app/chris/agent_selection.py  validated agent choice
backend/app/chris/agents.py   Agent type and the mock agent list
backend/app/chris/prompts.py  direct-answer system prompt
```

## Mock agents

With `CHRIS_USE_MOCK_AGENTS=true`, Chris routes against `MOCK_AGENTS` (Honors College, Engineering Advisor, Writing Center, Library). If an agent is chosen the reply says Chris would route there; no agent is called. Low confidence (below 0.7) or no match falls back to a direct answer.

## Data storage

Requests set `store: false`, so Gemini does not keep interactions (the default
is to store them for up to 55 days on the paid tier). Chris sends its own
history, so it does not use `previous_interaction_id`. Do not remove this
without a team decision on retention.

## Run

```
cd backend
uv sync
uv run uvicorn app.main:app --reload --env-file .env
```

Docs at http://localhost:8000/docs.

## Not migrated yet

Real agents and A2A calls, suggestions, auth and trust tiers, database, Open WebUI hook.
