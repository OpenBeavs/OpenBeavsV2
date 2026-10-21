# Chris (prototype)

Chris answers messages directly through Gemini. Agent routing is not migrated yet.

## API

`POST /chris/message`

```json
{ "message": "Hello", "history": [{ "role": "user", "content": "..." }] }
```

Returns `{ "response": "..." }`. `history` is optional (roles: `user`, `assistant`).
Errors: 400 empty message, 500 missing config, 503 model call failed.

## Config (`backend/.env`, git-ignored)

- `GEMINI_API_KEY`: Gemini API key
- `CHRIS_MODEL`: Gemini model id (no default)

## Layout

```
backend/app/main.py           mounts routers
backend/app/config.py         reads env vars
backend/app/chris/router.py   HTTP route
backend/app/chris/llm.py      Gemini Interactions API call; the only provider-specific file
backend/app/chris/agent_selection.py  validated agent choice (built, not wired in yet)
```

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

Agent routing and A2A calls, suggestions, auth and trust tiers, database, Open WebUI hook.
