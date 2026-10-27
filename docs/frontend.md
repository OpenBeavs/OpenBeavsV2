# Frontend setup and integration

The `frontend/` directory is the standalone OpenBeavs interface. It selectively
adapts the original WebUI's Chris chat and sidebar presentation, with a read-only
agent directory. It uses Svelte 4, SvelteKit 2, Vite 5, TypeScript and Tailwind 4.
The old Open WebUI Python backend is not required.

## Run locally

Use Python 3.12 and Node.js 22 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install ./backend -r backend/requirements-dev.txt
cd backend
alembic upgrade head
# Optional: populate the registered-agent directory.
python -m app.db.seed_agents
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Configure `GEMINI_API_KEY` and `CHRIS_MODEL` privately in the backend environment
or its ignored `.env` file before sending messages. Do not put model keys,
database credentials, or login tokens in frontend configuration. Backend startup
and `/health` can succeed even if model configuration or database tables are
missing. An empty agent table is valid: Chris answers directly.

In a second terminal, from the repository root:

```bash
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite (normally `http://127.0.0.1:5173`). The browser
calls relative `/health` and `/chris/*` paths. Vite proxies those requests to
`http://127.0.0.1:8000` in development and preview, avoiding cross-origin browser
requests. To use another backend, set the **non-secret server-side**
`BACKEND_ORIGIN` when starting Vite:

```bash
BACKEND_ORIGIN=http://127.0.0.1:9000 npm run dev
```

No backend API routes, CORS configuration, or database migrations are added by
this frontend. `BACKEND_ORIGIN` must be an origin you control; it is not embedded
as a browser API URL.

## Supported behavior

- `/`: Chris chat with plain-text message bubbles, loading/error states, and
  New Chat. Enter sends; Shift+Enter inserts a newline. IME composition does not
  submit. Only one request runs at a time.
- `/agents`: case-insensitive name/description search, featured flags, and access
  tiers. Restricted and role-gated agents are marked unavailable to guests.
- Collapsible desktop sidebar, keyboard-accessible mobile drawer, and theme
  toggle. The system theme is used until the user chooses one.

The typed client uses only `GET /health`, `GET /chris/agents`, and
`POST /chris/message`. Agent endpoint URLs remain metadata, never browser call
targets. Responses are complete JSON, not streams. Routing labels say **routing
preview** because Chris chooses an agent but does not yet invoke it. The agent
discovery card's streaming flag is not evidence of streaming support.

The layout owns the in-memory conversation, so moving between Chris and Agents
preserves it. Requests include prior successful turns, a random guest session
identifier, and the current hostname. A returned `chat_id` is reused with that
guest identifier; the backend then treats database history as authoritative.
Neither `user_id` nor old bearer tokens are sent. The prototype's user lookup is
not a verified authentication system.

Refresh and New Chat clear the visible conversation and identifiers, but do not
delete backend records. No transcript or guest token is saved to browser
storage. Only the theme preference is stored. Guest records receive a two-hour
expiry at creation; deletion depends on backend cleanup being invoked. This
frontend does not promise automatic deletion or expose the maintenance route.

If a response has no persisted chat ID, its reply is still displayed. The rest
of that conversation sends complete client history without a chat ID, even if
storage later recovers, avoiding a switch to an incomplete stored history.
Failures restore the input and remain outside conversation history. POSTs are
never retried automatically. Requests time out after 90 seconds; a backend may
still finish after the browser stops waiting, so a manual retry can duplicate a
turn. New Chat ignores any late response from the previous conversation.

SSO, saved-chat retrieval, direct agent calls, streaming, embedding, uploads,
Arena Mode, model controls, and administration are outside this initial port.

## Build, preview, and hosting

```bash
cd frontend
npm run build
npm run preview
```

The static application is emitted into `frontend/build/`. Preview includes the
same API proxy as development. A production static host must serve assets and
fall back to `index.html` for UI routes such as `/agents`. Its reverse proxy must
send `/chris/*` and `/health` to FastAPI **before** applying the SPA fallback.
Vite's proxy configuration does not ship inside the static files. Keep the
maintenance DELETE route outside public proxy access in a real deployment.
This change does not deploy a cloud service or establish production auth.

## Checks

```bash
cd frontend
npm run lint
npm run test
npm run build
npx playwright install chromium
npm run test:e2e
```

Browser tests run the built app against intercepted API fixtures, without model
keys or a live backend. On a machine with Chrome already installed,
`PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` uses that browser instead. Vitest
covers the actual typed client and conversation transitions. Playwright covers
navigation, rendering safety, input, errors, refresh, mobile keyboard behavior,
and the absence of unsupported API calls. These test dependencies are retained
only for development; no browser AI or Open WebUI runtime packages are needed.

From `backend/`, with the project virtual environment active:

```bash
PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:///:memory: pytest
ruff check .
```

`.github/workflows/checks.yml` runs the backend suite (including security-related
authorization cases), Ruff, frontend lint/type checks, unit tests, build, and
browser tests. Secret scanning and production dependency-policy gates remain
separate team work; this workflow does not claim to implement them.

For live acceptance, start the actual backend with initialized tables and model
configuration, send a greeting, receive a direct answer, then send a follow-up.
Confirm the second request reuses the returned chat ID and guest identifier, and
that the directory loads from the real database. This is separate from the
fixture-based browser suite and requires a working model service.

## Attribution

`frontend/static/THIRD_PARTY_NOTICES.txt` preserves the original repository's MIT
and Open WebUI BSD notices. The favicon, Chris presentation, sidebar styling,
and small icon patterns were adapted from that repository. This port does not
import a newer upstream Open WebUI release.
