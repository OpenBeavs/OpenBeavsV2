# Web UI

The SvelteKit app the Chat System serves to the browser. It draws the conversation and sends the person's actions to Application Services through the API.

- It builds with `adapter-static`, so in production every line runs in the browser. Server-side code belongs in `application-services/`.
- It runs on a machine the user controls, so it enforces nothing. A hidden tab or a sign-in screen changes what a person sees; Application Services makes the real check on every API call.
- It keeps the conversation in browser memory and sends the new message with the conversation's history.
- It draws each expert badge from the routing result Application Services returns with the reply, never from the reply's text.
- **Later:** it sends a conversation ID and the new message, and draws each badge from the source stored with the message.

Moved here from the dev branch: `frontend/`, and `docs/frontend.md`, which follows.

This folder is the standalone OpenBeavs interface. It selectively
adapts the original WebUI's Chris chat and sidebar presentation. It uses Svelte 4, SvelteKit 2, Vite 5, TypeScript and Tailwind 4.
The old Open WebUI Python backend is not required.

## Run locally

The [root README](../../README.md#install) installs this folder with the rest of the
repository and starts it with the other three services. Application Services answers
a chat message only when the Conversation Agent and the Agent Registry are running too.

To run only the Web UI, from the repository root, `make dev-front` starts Vite with the
launcher's settings: its port (8080 when `MICROSOFT_REDIRECT_URI` names it, otherwise
5173) and `BACKEND_ORIGIN=http://127.0.0.1:8010`, Application Services' address. With
npm directly, from this folder:

```bash
BACKEND_ORIGIN=http://127.0.0.1:8010 npm run dev
```

Open the local URL Vite prints (`http://127.0.0.1:5173` by default). The browser calls
relative paths, and Vite proxies `/health`, `/chat/message`, `/auth/*`, and `/oauth/*`
to `BACKEND_ORIGIN` in development and preview, so the browser makes no cross-origin
requests. When `BACKEND_ORIGIN` is unset, Vite proxies to `http://127.0.0.1:8010`,
where the launchers run Application Services. It is a server-side setting, not a
browser secret, and it must be an origin you control. Do not put model keys, database
credentials, or login tokens in the Web UI's configuration.

The Web UI adds no API routes, CORS configuration, or database migrations.

## Supported behavior

- `/`: Chris chat with Markdown replies, plain-text guest messages, loading/error states, and
  New Chat. Enter sends; Shift+Enter inserts a newline. IME composition does not
  submit. You can type the next draft while Chris replies. Send stays disabled
  until the current request finishes.
- Collapsible desktop sidebar, keyboard-accessible mobile drawer, and theme
  toggle. The system theme is used until the user chooses one.

The typed client uses only `GET /health` and `POST /chat/message`. Agent endpoint
URLs never reach the browser. Responses are complete JSON, not streams. The backend returns a structured
`routing` metadata. Expert replies show “Answered by” followed by the registered
`agent_name`. Direct Gemini replies have no expert attribution. Backend
failures use a generic notice outside the transcript; failed turns are not added to
browser history or replayed on the next request.

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

An agent directory, a sign-in screen, saved-chat retrieval, direct agent calls, streaming, embedding, uploads,
Arena Mode, model controls, and administration are outside this initial port.

## Build, preview, and hosting

```bash
cd chat-system/web-ui
npm run build
npm run preview
```

The static application is emitted into `chat-system/web-ui/build/`. Preview includes the
same API proxy as development. A production static host must serve assets and
fall back to `index.html` for UI routes. Its reverse proxy must
send `/chat/message`, `/health`, `/auth/*`, and `/oauth/*` to Application Services
**before** applying the SPA fallback. Vite's proxy configuration does not ship
inside the static files. Proxy only these routes.
This folder holds no deployment configuration.

## Checks

```bash
cd chat-system/web-ui
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

`npm run test:pipeline` additionally starts the real Application Services, Chris, and
registry code with a scripted model, using `tests/end-to-end/`'s environment, so run
`uv sync --locked` in that folder first. It uses temporary SQLite databases, one for
Chat and one for the registry, unless `TEST_CHAT_SYSTEM_DATABASE_URL` and
`TEST_REGISTRY_DATABASE_URL` name a PostgreSQL server
([Test against it](../../shared-resources/postgres/README.md#test-against-it)). It
exercises selection, history, no match, revocation, malformed model output, and
timeout/error recovery through the browser. Neither suite requires a real model key.

In `.github/workflows/checks.yml`, the `web-ui` job runs the lint and type checks, unit
tests, build, and browser tests, and the `end-to-end` job runs the pipeline test against
PostgreSQL 16, with each owner signed in under its own login. Secret scanning and
production dependency-policy gates remain separate team work; this workflow does not
claim to implement them.

For live acceptance, start the stack as the [root README](../../README.md#start) says
and ask an OSU question followed by a related question in the same chat. Expect the
selected expert's answer and attribution ([What to expect](../../README.md#what-to-expect)).
Confirm prior successful turns are sent from browser memory. This requires a working
model and key and is distinct from deterministic tests.

## Attribution

`static/THIRD_PARTY_NOTICES.txt` preserves the original repository's MIT
and Open WebUI BSD notices. The favicon, Chris presentation, sidebar styling,
and small icon patterns were adapted from that repository. This port does not
import a newer upstream Open WebUI release.
