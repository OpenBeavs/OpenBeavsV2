# Frontend setup and integration

The `frontend/` directory is the standalone OpenBeavs interface. It selectively
adapts the original WebUI's Chris chat and sidebar presentation, with a read-only
agent directory. It uses Svelte 4, SvelteKit 2, Vite 5, TypeScript and Tailwind 4.
The old Open WebUI Python backend is not required.

## Run locally

Follow [the registry setup guide](registry.md#local-development-setup) for backend dependencies,
migrations, model configuration, and all three terminals. It runs Chat/Chris at
`http://127.0.0.1:8010` and the standalone registry at `http://127.0.0.1:8001`.
Use Python 3.12 and Node 22 or newer.

In `frontend/`, after `npm ci`, start Vite with the backend proxy origin:

```powershell
$env:BACKEND_ORIGIN='http://127.0.0.1:8010'
npm run dev
```

Open the Local URL printed by Vite (normally `http://127.0.0.1:5173`). The browser
calls relative `/health` and `/chat/*` paths. Vite proxies them to `BACKEND_ORIGIN`,
which defaults to port 8000 if unset. It is a server-side setting, not a browser secret.
Do not put model keys, database credentials, or login tokens in frontend configuration.

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

The typed client uses only `GET /health`, `GET /chat/agents`, and
`POST /chat/message`. Agent endpoint URLs remain metadata, never browser call
targets. Responses are complete JSON, not streams. The backend returns a structured
`routing` result, which is rendered as a selected-expert, no-match, or error card.
Selected-expert display fields come from Chat's agents table; expert endpoints are
not exposed by the routing response. No expert is called. Optional Gemini fallback
answers are displayed as text when `CHRIS_SELECTION_ONLY=false`. Development mode
shows a banner explaining the local demo's authentication and selection boundaries.

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
send `/chat/*` and `/health` to FastAPI **before** applying the SPA fallback.
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
npm run test:pipeline
```

The original browser tests run the built app against intercepted API fixtures, without model
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

`test:pipeline` additionally starts the real Chat/Chris/registry code with a scripted
model and a temporary SQLite database. It exercises selection, history, no match,
revocation, malformed model output, and timeout/error recovery through the browser.
Both suites run in CI; neither requires a real model key.

For live acceptance, follow the runbook and ask an OSU question followed by a related
question in the same chat. Expect a selection card, not the expert's answer. Confirm
the chat ID and guest identifier are reused and the directory loads from SQLite.
This requires a working registry model/key and is distinct from deterministic tests.

## Attribution

`frontend/static/THIRD_PARTY_NOTICES.txt` preserves the original repository's MIT
and Open WebUI BSD notices. The favicon, Chris presentation, sidebar styling,
and small icon patterns were adapted from that repository. This port does not
import a newer upstream Open WebUI release.
