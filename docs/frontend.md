# Frontend setup and integration

The `frontend/` directory is the standalone OpenBeavs interface. It selectively
adapts the original WebUI's Chris chat and sidebar presentation, with a read-only
agent directory. It uses Svelte 4, SvelteKit 2, Vite 5, TypeScript and Tailwind 4.
The old Open WebUI Python backend is not required.

## Run locally

Use Python 3.12, uv, and Node.js 22 or newer. From the repository root:

```bash
cd backend
uv sync
uv run alembic upgrade head
# Optional: populate the registered-agent directory.
uv run python -m app.db.seed_agents
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Follow [the root README](../README.md#run-locally-windows-powershell) for backend dependencies,
migrations, model configuration, and the all-services launcher. It runs the backend at
`http://127.0.0.1:8010`, Chris at port 8000, and the registry at port 8001.
Use Python 3.12 and Node 22 or newer.

In `frontend/`, after `npm ci`, start Vite with the backend proxy origin:

```powershell
$env:BACKEND_ORIGIN='http://127.0.0.1:8010'
npm run dev
```

Open the local URL printed by Vite (normally `http://127.0.0.1:5173`). The browser
calls `/health`, `/chat/message`, and `/chat/agents`. Vite proxies those requests to
`http://127.0.0.1:8000` in development and preview, avoiding cross-origin browser
requests. To use another backend, set the **non-secret server-side**
`BACKEND_ORIGIN` when starting Vite:

```bash
BACKEND_ORIGIN=http://127.0.0.1:9000 npm run dev
```
Open the Local URL printed by Vite (normally `http://127.0.0.1:5173`). The browser
calls relative `/health` and `/chat/*` paths. Vite proxies them to `BACKEND_ORIGIN`,
which defaults to port 8000 if unset. It is a server-side setting, not a browser secret.
Do not put model keys, database credentials, or login tokens in frontend configuration.

No backend API routes, CORS configuration, or database migrations are added by
this frontend. `BACKEND_ORIGIN` must be an origin you control; it is not embedded
as a browser API URL.

## Supported behavior

- `/`: Chris chat with Markdown replies, plain-text guest messages, loading/error states, and
  New Chat. Enter sends; Shift+Enter inserts a newline. IME composition does not
  submit. You can type the next draft while Chris replies. Send stays disabled
  until the current request finishes.
- `/agents`: case-insensitive name/description search, featured flags, and access
  tiers. Restricted and role-gated agents are marked unavailable to guests.
- Collapsible desktop sidebar, keyboard-accessible mobile drawer, and theme
  toggle. The system theme is used until the user chooses one.

The typed client uses only `GET /health`, `GET /chat/agents`, and
`POST /chat/message`. Agent endpoint URLs remain metadata, never browser call
targets. Responses are complete JSON, not streams. The backend returns a structured
`routing` metadata, but the UI renders all successful replies as plain message bubbles.
It shows no expert IDs, confidence, routing cards or diagnostic explanations. Backend
failures use a generic notice outside the transcript; failed turns are not added to
browser history or replayed on the next request. No expert is called yet.

The layout keeps each guest chat, draft, and pin in memory while the tab is open.
New Chat opens a separate conversation, and the sidebar lets you switch between
chats or pin them. A pending reply stays with the chat that sent it.
Requests include prior successful turns and the current hostname. Guest tokens,
chat IDs and user IDs are not sent. The backend uses only the supplied history
and never reads or writes conversation records. Replies retain `chat_id: null`
for wire compatibility; this is normal and does not show a storage warning.

Refreshing or closing the tab clears the local chat list and pins. No transcript
is saved to browser storage or the application database. Only the theme preference
is stored. Previously stored guest transcripts remain until the database owner
removes them.

Failures restore the sent text if the composer is empty. If you've started
another draft, the failed text is available in the error notice and your draft
stays in the composer. Failed messages stay outside conversation history. POSTs are
never retried automatically. Requests time out after 90 seconds; a backend may
still finish after the browser stops waiting, so a manual retry can duplicate a
turn.

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
send only the exact paths `/chat/message`, `/chat/agents`, and `/health` to FastAPI
**before** applying the SPA fallback. Vite's proxy configuration does not ship
inside the static files. Proxy only the supported public routes.
This change does not deploy a cloud service or establish production auth.

## Checks

```bash
cd frontend
npm run lint
npm run test
npm run build
npx playwright install chromium
npm run test:e2e
npm run test:pipeline
```

The original browser tests run the built app against intercepted API fixtures, without model
keys or a live backend. On a machine with Chrome already installed,
`PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` uses that browser instead. Vitest
covers the typed client and conversation transitions and tests the dev and preview
proxy against a loopback stub. Playwright covers
navigation, rendering safety, input, errors, refresh, mobile keyboard behavior,
and the absence of unsupported API calls. These test dependencies are retained
only for development; no browser AI or Open WebUI runtime packages are needed.

From `backend/`:

```bash
uv sync --locked
uv run ruff check .
PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:///:memory: uv run pytest
```

`.github/workflows/checks.yml` runs the backend suite (including security-related
authorization cases), Ruff, frontend lint/type checks, unit tests, build, and
browser tests. Secret scanning and production dependency-policy gates remain
separate team work; this workflow does not claim to implement them.

`test:pipeline` additionally starts the real Chat/Chris/registry code with a scripted
model and a temporary SQLite database. It exercises selection, history, no match,
revocation, malformed model output, and timeout/error recovery through the browser.
Both suites run in CI; neither requires a real model key.

For live acceptance, follow the runbook and ask an OSU question followed by a related
question in the same chat. With `CHRIS_SELECTION_ONLY=false`, expect the selected expert's answer. Selection-only diagnostics return a generic specialist acknowledgement. Confirm
prior successful turns are sent from browser memory and the directory loads from SQLite.
This requires a working registry model/key and is distinct from deterministic tests.

## Attribution

`frontend/static/THIRD_PARTY_NOTICES.txt` preserves the original repository's MIT
and Open WebUI BSD notices. The favicon, Chris presentation, sidebar styling,
and small icon patterns were adapted from that repository. This port does not
import a newer upstream Open WebUI release.
