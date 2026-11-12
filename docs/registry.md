# Agent Registry

The registry is how an A2A agent gets into OpenBeavs and how Chris decides it may
route to it. An agent is submitted by URL and must pass a set of automated checks.
In the default **auto** mode an agent that passes goes live as `provisional`;
in **manual** mode it waits for an admin to approve it.

It is a module of the backend (`backend/app/registry/`) that writes to the unified
`agents` table described in `docs/db_docs/database-architecture.md`. There is no
separate registry database. Registry management remains in the main backend; A2A
selection runs as a standalone service sharing the configured `agents` table.

## How an agent gets in

```
submit URL -> safe-address check -> fetch + clean + validate card -> wording check -> decision
                                                                                        |
        auto mode (default): clean card -> "provisional" (live)   flagged card -> "pending"
        manual mode:         every card -> "pending" (waits for an admin)
                                                                                        |
                              Chris routes only to "approved" and "provisional"
```

1. **Submit.** `POST /registry/agents` with `{"url": "..."}`. Nothing else is accepted.
2. **Fetch.** The hub requests the agent's discovery card (`/.well-known/agent.json`)
   after checking the address is safe (see Security). The card is validated.
3. **Decision** (`REGISTRY_APPROVAL_MODE`, see Approval mode below).
   - **auto** (default): a card that passed every check, with no warning flag, is
     stored as `provisional` and active, so Chris can route to it at once. It is
     recorded as reviewed by `system:auto`. A card flagged for steering wording is
     held as `pending`.
   - **manual**: the agent is stored with `status = pending` and `is_active = false`.
     Only the submitter and admins can see it. Chris cannot route to it.
4. **Review.** An admin calls `POST /registry/agents/{id}/review`. `approve` and
   `provisional` make the agent active and visible; `revoke` and `reject` make it
   inactive and hidden. The reviewer and time are recorded. This still works on
   auto-approved agents, so any of them can be revoked.
5. **Selection.** Chris asks the registry over A2A. The registry offers its model only
   active agents whose status is `approved` or `provisional`, with public access and
   no required role (`service.routable_agents`). It rechecks eligibility before returning
   a selection. Chris does not invoke the selected expert yet.

## Statuses

| Status | Routable by Chris | Visible to other users | Meaning |
|---|---|---|---|
| `pending` | no | no (submitter and admins only) | Submitted, awaiting review (manual mode, or a card held by the wording check) |
| `approved` | yes | yes | Reviewed and accepted |
| `provisional` | yes | yes | Accepted for a pilot. Auto mode uses this status for agents that passed the automated checks; a UI warning is not implemented here |
| `revoked` | no | no (submitter and admins only) | Rejected or withdrawn |

Routability also requires active state, public access, and no required role.

`status` has no database default, so a row can never become routable by omission.
`trust_tier` (`public` / `authenticated` / `privileged`) is a separate gate for *who
may use* an agent. It defaults to `public` and only an admin review can change it.

## Approval mode

Human approval (an admin screen, real sign-in for admins) is planned for later work.
Until then the registry decides by itself:

| `REGISTRY_APPROVAL_MODE` | A card that passes every check | A card flagged by the wording check |
|---|---|---|
| `auto` (default; also used when blank) | `provisional`, active, routable | `pending` |
| `manual` | `pending` | `pending` |

Any other value is treated as `manual`. No database change is involved: `provisional`
already exists and `reviewed_by` records `system:auto`.

**No person looks at an auto-approved agent before it goes live**, and Chris sends
user questions to the endpoint of any live agent. This is acceptable for the MVP only
because submission requires authentication, which is not implemented for production
(see Authentication), so in a deployment nobody can submit and only seeded agents are
live. Before submission is opened, add at least: a check that the endpoint answers, a
limit per submitter, and the review workflow. Until then use `manual` wherever
submission is open to people you do not trust.

## The registry as an A2A agent (expert selection)

The registry is also an **A2A agent** whose one job is to choose which registered
expert should handle a user's question. The registry never calls the expert and never
answers the question. It reads only agents that are currently routable
(`routable_agents()`: active, `approved` or `provisional`, public, no required role).

**Status.** The local frontend -> Chat -> Chris -> registry A2A selection flow is
built and tested. Chris returns a plain selection acknowledgement or a Gemini answer.
Backend errors stay in terminal logs; if no answer is available the UI shows a generic notice.
The selected expert is not called yet. See [Local development setup](#local-development-setup)
for the complete setup and [Workflow validation](#workflow-validation) for testing.

```text
Frontend --POST /chat/message--> Chat API --A2A--> Chris --A2A--> Registry
Frontend <--plain message------ Chat API <------ Chris <------- selected ID + endpoint / none / error
```

It uses A2A **protocol 1.0** through the official `a2a-sdk`. The card's `version`
(`0.1.0`) is the registry agent's own software version, separate from the protocol
version (`supportedInterfaces[].protocolVersion = "1.0"`). The same endpoint also
answers A2A 0.3 clients that send `A2A-Version: 0.3`.

### Where it lives

| What | Address |
|---|---|
| Agent Card (public) | `GET /a2a/registry/.well-known/agent-card.json` (also `.../agent.json`) |
| A2A endpoint | `POST /a2a/registry/` (use the `url` from the card; the trailing slash matters) |

Run the registry separately from Chat/Chris with
`uvicorn app.registry.a2a_app:create_standalone_app --factory`.
See [Registry code layout](#registry-code-layout) for module responsibilities.

The standalone service also serves two probe routes, neither of which needs a token:

| Route | Meaning |
|---|---|
| `GET /health` | **Liveness.** The process is up. Never touches the database or the model. |
| `GET /ready` | **Readiness.** 200 only if the `agents` table can be read (including the registry's review columns, so an unmigrated database is reported), `REGISTRY_PUBLIC_URL` is usable, A2A authentication is usable, and `REGISTRY_MODEL` and a Gemini key are set. Otherwise 503. It **never calls Gemini**, so it costs nothing. The body is `{"status": "ready" or "not_ready", "checks": {...}}` with `database`, `public_url`, `auth`, `model` and `model_key` each `ok` or `failed`. It never contains setting values, connection details or error text (logs name the failing variable only). It checks that a key is *set*, not that Google accepts it. |

The main backend (`app.main:app`) has only `/health`; `/ready` belongs to the standalone
registry service. Use `/health` for the Cloud Run liveness probe and `/ready` for startup or
readiness checks and for deployment verification. `/ready` is public like `/health`; it
reveals only which of those five checks pass.

### The contract Chris builds against

Send an A2A `SendMessage` (protocol 1.0, with the header `A2A-Version: 1.0`; the SDK
client adds it for you) whose message has:

- a **text part**: the user's question (required, at most 4,000 characters);
- optionally a **data part** `{"history": [{"role": "user" | "assistant", "content": "..."}]}`
  (the last 6 turns are used, each cut to 1,000 characters).

**History precedence.** The data part is the contract. As a compatibility bridge the
registry also accepts the same list in the request-level `metadata.history`, but only
when no data part carries a `history` list; when both are present the data part wins and
the metadata is ignored (never merged). An empty data-part list still counts as present.
Malformed entries are skipped and the same limits apply to both sources.

The reply is trimmed to **what Chris needs and nothing more**: one agent message with
a single **text part** holding compact JSON, exactly one of

```json
{"agent": {"id": "<agent id>", "endpoint_url": "https://..."}}
```
```json
{"agent": "none"}
```

There is no name, description, confidence, reason, card URL, status or schema field. Both
values come from the registry's own record, never from the model or the caller, and the
record is **re-read just before replying**: if the expert was revoked, deactivated or
otherwise made ineligible while the model was working, there is no selection (see
`agent_unavailable` below), and if it was edited the reply carries the current endpoint.
Chris's strict check accepts exactly these shapes and rejects anything else. Anyone who
needs the name or description looks the id up (Chat reads its own `agents` table).

| Reply | Meaning | What Chris does |
|---|---|---|
| `{"agent": {"id", "endpoint_url"}}` | An expert fits (confidence at least 0.7; the threshold is an initial guess). | Return a structured selection to Chat; no expert is called yet. |
| `{"agent": "none"}` | Nothing fits, or nothing is registered. A normal answer. | Report no match (or answer directly, in fallback mode). |
| an A2A error | The registry could not decide. The JSON-RPC error **message is a short code** (below) and nothing else: no internal detail. `invalid_request` is `-32602`; every other code is `-32603`. | Report the failure; retry later only if the code is retryable. |

Error codes (the error's `message`):

| Code | Retryable | Meaning |
|---|---|---|
| `invalid_request` | no | No question text, or it is over 4,000 characters |
| `not_configured` | no | `REGISTRY_MODEL` or the Gemini key is missing |
| `selection_unavailable` | yes | The Gemini request failed |
| `selection_busy` | yes | Too many model calls at once and none freed up in time (see Limits and overload) |
| `invalid_model_reply` | yes | The model's reply was unusable or named an agent that is not eligible |
| `agent_unavailable` | yes | The chosen expert stopped being eligible before the reply (for example it was revoked) |
| `registry_capacity_exceeded` | no | More than 50 experts are eligible. Selection does not silently drop any; an operator has to raise `MAX_CANDIDATES` in `selection.py` (and check the prompt size) or revoke agents. No model call is made |
| `registry_unavailable` | yes | The agents table could not be read |
| `internal_error` | yes | Unexpected failure |

Retryability is not on the wire; the receiver keeps this table. The SDK logs a failed
selection at error level on the registry (it is how it reports a raised A2A error).

Protocol-level problems use the standard errors (bad JSON `-32700`, unknown method
`-32601`, bad params `-32602`, unsupported version `-32009`). A request without the
`A2A-Version` header is treated as 0.3 and refused.

**For future expert dispatch (not implemented).** Use `card_url` (stored with the agent) to find each expert's
card: the seeded experts differ (the Math agent publishes only `/.well-known/agent.json`;
the OSU agent publishes `agent-card.json` under its own path), and the experts we have
checked advertise A2A 0.3.0. Before calling `agent.endpoint_url`, validate it again with
`app/registry/security.py` (it was checked only when the agent was registered, and the
DNS-rebinding limitation above applies).

### Authentication

Callers authenticate with a **Google-issued ID token** (an `Authorization: Bearer`
header) in Google auth mode. Chris does not fetch or attach these tokens yet; that
caller-side integration remains deployment work. The registry verifies the
signature, expiry and audience, requires a verified email, and requires that email to
be in `REGISTRY_A2A_ALLOWED_CALLERS`. The Agent Card is public so clients can discover
the agent; every other request needs a token.

The check is in the application because Cloud Run IAM protects a whole service, not
one route. Limitation: the caller's identity is its service account, so everything
that runs as an allowed account counts as the same caller. If the registry is deployed
as its own private service, Cloud Run IAM can also enforce who may invoke it.

| Variable | Purpose |
|---|---|
| `REGISTRY_PUBLIC_URL` | The origin clients use, put in the card and used as the default token audience. Must be a bare origin (`https://host[:port]`: no path, query, fragment or credentials). Default `http://127.0.0.1:8000`; **required on Cloud Run, where it must be https**. A missing or malformed value makes the A2A agent answer 503 and `/ready` report `public_url: failed` |
| `REGISTRY_A2A_AUTH` | `google`, or `dev` (no authentication, local only). Unset means `dev` locally and `google` anywhere else |
| `REGISTRY_A2A_ALLOWED_CALLERS` | Comma-separated service-account emails allowed to call it. Empty means every request is refused (503) |
| `REGISTRY_A2A_AUDIENCE` | Token audience; defaults to `REGISTRY_PUBLIC_URL` |
| `REGISTRY_MODEL` | **Required.** The Gemini model used to choose an expert. Chris's settings are never read |
| `REGISTRY_GEMINI_API_KEY` | The registry's own Gemini API key (a secret). Falls back to the generic `GEMINI_API_KEY`. Without a key and a model the reply is `error: not_configured` |
| `REGISTRY_MODEL_TIMEOUT_SECONDS` | One Gemini request's timeout. Default `8`, allowed 1 to 60. An overall asyncio deadline bounds the model request. Allow additional queue, database, discovery and response time in the caller |
| `REGISTRY_MODEL_MAX_CONCURRENCY` | Simultaneous Gemini calls **per process**. Default `8`, allowed 1 to 64; anything else is ignored with a warning |
| `REGISTRY_MODEL_QUEUE_SECONDS` | How long a request may wait for a free slot before it gets `selection_busy`. Default `2`, allowed 0 to 60 (`0` refuses at once when all slots are taken) |

`dev` mode is refused on Cloud Run and with a non-local `DATABASE_URL` (the same rules
as `REGISTRY_DEV_AUTH`); anything misconfigured fails closed.

### Limits and overload

Each request that reaches the model is a paid Gemini call, so the number running at the
same time is capped by `ModelLimiter` in `llm.py`. A request waits up to `REGISTRY_MODEL_QUEUE_SECONDS`
for a slot and is then answered with the retryable `error: selection_busy`.
Chris reports the failure in selection-only mode; optional fallback may answer directly. A request that is refused never
reaches Gemini, and a slot is released when a call succeeds, fails or is cancelled.
The Gemini call itself times out after 8 seconds.

The defaults (8 at once, 2 seconds) are development values, not tuned numbers. Tune
them against Gemini's quota and observed latency.

**The limit is per process.** It is not shared between uvicorn workers or between Cloud Run
instances, so the ceiling for the whole service is
`REGISTRY_MODEL_MAX_CONCURRENCY x workers per instance x instances`. With the defaults, one
worker per instance and `--max-instances 3` that is at most 24 simultaneous model calls.
For a limit that holds across the service, also set Cloud Run `--max-instances` (and
`--concurrency`, which caps requests per instance before this code sees them) and a quota
or budget alert on the Gemini key. This is concurrency control, not a rate limit per
caller or per minute; one allowed caller can still use the whole capacity.

Selection supports at most 50 eligible experts. Above that the reply is
`registry_capacity_exceeded` (and the server logs an error with the counts) rather than
quietly leaving experts out.

Logs never contain the model's reply, values it got wrong, or an agent id it made up:
unusable replies are logged as field names and error kinds only.

### Registry code layout

| File | Responsibility |
|---|---|
| `a2a.py` | Agent Card, request/reply adapter, database eligibility recheck |
| `a2a_app.py` | Standalone service, origin validation, health/readiness |
| `a2a_auth.py` | Google/local caller verification and request body limit |
| `selection.py` | Prompt/schema construction and decision validation |
| `llm.py` | Gemini request, overall deadline and per-process concurrency limit |

### Query the registry directly

After completing [Local development setup](#local-development-setup), from `backend/`
in another terminal:

```powershell
.venv\Scripts\python.exe scripts\registry_a2a_client.py "What majors does OSU offer?"
```

The default URL is `http://127.0.0.1:8001/a2a/registry`. For a different origin, set
`REGISTRY_PUBLIC_URL` before starting the service and pass the matching `--url` to
this client. For a deployed private registry, the script reads `REGISTRY_A2A_TOKEN`
from its private process environment. Never paste tokens into commands or logs.
Chris itself does not attach that token yet.

## Endpoints

| Method and path | Who | What |
|---|---|---|
| `POST /registry/agents` | signed-in user | Submit by URL. 201 with a provisional or pending entry according to approval mode; 400 for an unsafe or invalid card; 409 if the card URL is already registered; 422 if the body has anything but `url` |
| `GET /registry/agents` | signed-in user | List what the caller may see. Optional `?status=` |
| `GET /registry/agents/{id}` | signed-in user | One entry, or 404 if it does not exist or is not visible |
| `POST /registry/agents/{id}/review` | admin | Body: `action` (`approve`, `provisional`, `revoke`, `reject`), optional `note`, `trust_tier`, `required_role`, `is_featured` |

Submitter and review details (`submitted_by`, `reviewed_by`, `reviewed_at`,
`review_note`) are returned only to admins and to the submitter.

Chris's own listing, `GET /chris/agents`, returns the routable agents.

## Where each stored field comes from

| Field | Source |
|---|---|
| `id` | Generated by the hub (UUID). Not read from the card |
| `name`, `description`, `skills`, `capabilities` | The agent card, validated (name at most 128 characters, description at most 4000, at most 50 skills) |
| `card_url` | The address the hub fetched. A submitted URL without `/.well-known/` becomes `<scheme>://<host>/.well-known/agent.json`; any path on it is dropped, so paste the full card URL for an agent hosted under a path |
| `endpoint_url` | The endpoint the card advertises, chosen as described under "Which endpoint is stored" and checked with the safe-URL rules. Its path and query are preserved; a missing or invalid endpoint rejects the submission rather than guessing from the discovery address |
| `trust_tier`, `is_featured`, `status`, `is_active` | Set by the server or by an admin review, never by the submitter |
| `submitted_by` | The caller's email |

## Security

- **Safe URLs.** The hub fetches submitted URLs from its own server, so it refuses
  anything that could reach internal systems: plain `http` (unless
  `REGISTRY_ALLOW_HTTP`), credentials in the URL, `localhost`,
  `metadata.google.internal`, and any host resolving to a loopback, private,
  link-local (including the cloud metadata address `169.254.169.254`), multicast,
  reserved or carrier-grade-NAT address, IPv4 or IPv6.
- **Which endpoint is stored.** Two card formats are accepted and the choice is explicit.
  A2A 1.0 cards list `supportedInterfaces`: only entries with `protocolBinding`
  `JSONRPC` (any case) and a `protocolVersion` of 1.x or 0.3 qualify, the newest version
  wins, and the card's order breaks ties. If the list is present but nothing qualifies
  the card is rejected; it never falls back to a top-level `url`. Older cards (no
  `supportedInterfaces`, or an empty list) use the top-level `url`, which must be
  JSON-RPC: `preferredTransport` absent or `JSONRPC`, otherwise a JSON-RPC entry of
  `additionalInterfaces` is used. Only the chosen endpoint is stored, and a chosen
  endpoint that fails a safety check rejects the card (another entry is never swapped
  in). The protocol version and binding of the chosen entry are **not stored** (no
  schema change); a caller learns them from the agent's card at `card_url`.
- **Advertised endpoint.** The chosen endpoint must be a non-empty absolute URL. The registry independently checks its scheme, credentials, hostname, and resolved addresses, including when it differs from the card host. Paths such as `/rpc`, trailing slashes, and query strings are preserved. Relative URLs, fragments, backslashes, and embedded whitespace/control characters are rejected. `REGISTRY_ALLOW_HTTP` applies to both addresses but never permits private destinations. This is submission-time validation, not proof of endpoint availability; the existing DNS-rebinding limitation still applies. Existing database records are not rewritten.
- **Bounded fetch.** No redirects are followed. The hub asks for an uncompressed
  card (`Accept-Encoding: identity`) and rejects any compressed response, so a small
  download cannot expand in memory. The body is capped at 100 KB (an oversized
  `Content-Length` is refused before reading) and must be valid JSON; malformed or
  deeply nested JSON is a clean 400, not a server error. The whole fetch, including
  DNS lookups, connecting, downloading and validating the advertised endpoint, has a
  10 second deadline (3 seconds to connect, 8 per read or write). It runs on a worker thread
  and the request stops waiting at the deadline even if a lookup or connection is
  stuck. A fixed internal limit allows **8 outstanding fetch workers per backend
  process**. When all slots are occupied, new fetches immediately raise a controlled
  `CardError` (the submission route returns 400 with a capacity-exhausted, try-again
  message); no worker is created and requests are not queued. Python cannot kill a
  thread: a timed-out worker keeps its slot until its work and client cleanup end.
  Blocked DNS or socket calls can outlast the caller's timeout. Cancellation is
  checked between fetch/validation steps so abandoned work stops when practical.
  Slots are released on success or failure; workers hold no database session.
  Clients created by the registry are closed by their worker. A client passed in
  by a caller is never closed by the registry. The limit is per process, not shared
  across deployment replicas, and requires no environment variable.
- **Untrusted card text.** Card text reaches Chris's prompts, so it is cleaned before
  it is stored: control characters (including newlines), zero-width and
  direction-override characters are removed and whitespace is collapsed. Skill ids and
  names and each tag are limited to 64 characters, a skill to 10 tags, and each skill
  must be an object or a string. Out-of-bounds cards are rejected with a message.
- **No self-service trust.** A submission cannot set its own status, tier, id or
  active flag (a request with any extra field is rejected).
- **Admin-only decisions.** Only admins can review; a submitter cannot approve their
  own agent.
- **Prompt-injection flag.** Card text that tries to steer Chris's routing (for
  example "ignore all previous instructions") is flagged in `review_note` for the
  reviewer. It does not block the submission, because the human review is the control.
- **Fail closed.** With no authentication configured every registry route answers 501.

**Known limitation (deferred): DNS rebinding.** The host is resolved when it is
checked and again when the connection is made, so a hostile DNS server could answer
"public" the first time and "internal" the second. The fix is to connect to the
validated address (IP pinning) or to use an egress proxy; it is not part of this MVP.

Restrictions this creates for the MVP:

- Nothing in a production deployment can trigger a card fetch: submission needs
  authentication, which is not implemented, so the registry routes answer 501 there
  (see Authentication). This is a property of the current MVP configuration, not a
  permanent guarantee.
- Nothing calls a stored agent endpoint yet (Chris's A2A client is a stub). The
  endpoint is validated only when the agent is submitted. **Before any code calls
  `endpoint_url`** (the A2A client), it must re-validate the address and connect to
  the validated IP, otherwise a rebinding agent could redirect the call to an internal
  service. Seeded agents are trusted and were not fetched by the registry.

## Authentication

v2 has no authentication yet (SSO is Phase 4 of the database plan). The registry
reads the caller through one function, `current_principal` in
`backend/app/registry/auth.py`. Replace it with verification of the OSU Microsoft SSO
token and nothing else in the registry changes.

**Production approval is not operational yet.** Without verified authentication the
registry routes (including approve, provisional and revoke) answer 501 in a
deployment; agents there are managed by seeds and migrations only. The review code
and its tests are in place for when SSO replaces `current_principal`.

| Variable | Purpose |
|---|---|
| `REGISTRY_DEV_AUTH` | `true` reads the caller from the `X-User-Id` and `X-User-Email` headers. **Local development and tests only: these headers are trivially forged.** Unset (the default) makes every route return 501 |
| `REGISTRY_ADMIN_EMAILS` | Comma-separated admin emails (not a secret) |
| `REGISTRY_ALLOW_HTTP` | `true` allows plain `http` card URLs. Local development only |
| `REGISTRY_APPROVAL_MODE` | `auto` (default) or `manual`; see Approval mode |
(The A2A settings are listed under "The registry as an A2A agent".)

`REGISTRY_DEV_AUTH` is refused, with a 501 and a logged reason, when the process looks
like a deployment, and the app refuses to start in that combination:

- a Cloud Run variable (`K_SERVICE`, `K_REVISION` or `K_CONFIGURATION`) is set; or
- `DATABASE_URL` is not SQLite or a Postgres server on this machine. Every host the
  connection could use counts, including `?host=` and `?hostaddr=` overrides, host
  lists and `?service=`, so `postgresql://u:p@localhost/db?host=db.example.test`
  is treated as remote.

A `backend/.env` file is loaded automatically, so keep `REGISTRY_DEV_AUTH` out of any
`.env` that is copied into a deployment.

`DATABASE_URL` selects the database as for the rest of the backend.

## Database

The registry adds review columns to `agents` (revision `a7c3e91d5b02`): `status`,
`submitted_by`, `reviewed_by`, `reviewed_at`, `review_note`, and a unique constraint on
`card_url`. Existing rows are backfilled to `approved` so Chris keeps routing to them.

Applying it to an existing Cloud SQL database depends on how that database was built:

1. Check for Alembic's version table (read-only):
   `SELECT version_num FROM alembic_version;`
2. **It returns `5f055aea1c94`:** run `alembic upgrade head` (from `backend/`, with
   `DATABASE_URL` set).
3. **The table does not exist** (the database was created from
   `create_tables_cloud.sql`): run `docs/db_docs/migrate_agents_registry.sql`, then
   after verifying that **all tables and constraints** match that revision,
   `alembic stamp a7c3e91d5b02` so Alembic knows the state, then `alembic upgrade head`.
   Rehearse this against a disposable PostgreSQL copy before touching Cloud SQL;
   do not stamp a revision based only on the presence of the agents table.
4. Verify: `SELECT id, name, status, is_active FROM agents;` shows every existing
   agent as `approved`.

Take a Cloud SQL backup first. The SQL file ends with its rollback statements.

### Chris is not a registered agent (revision `d4f1b8a2c967`)

Chris is the orchestrator. His discovery card (`GET /chris/.well-known/agent.json`) is
served by code and he is never offered to the router, so he has no row in `agents`.
Neither seed (`seed_agents.py`, `seed_agents.sql`) inserts him any more, and the new
migration `d4f1b8a2c967` (after `a7c3e91d5b02`) removes the row the early seed created:
it sets `chats.agent_id` to NULL for Chris, then deletes `id = 'chris'`. Chats and
messages are kept (`chats.agent_id` is `ON DELETE SET NULL` and messages belong to
chats). It touches nothing else and is safe to run when the row is already gone.
`routable_agents()` still excludes the id `chris`, so the code is safe before or after
the migration.

Downgrade restores only the originally seeded Chris row (and does nothing if one
exists). It cannot restore which chats used to reference Chris or any edits made to
his row after the upgrade.

**Deployment.** Whoever owns Cloud SQL migrations (Dean, with Jiya approving access)
takes a backup, then runs `alembic upgrade head` from `backend/` (after the
`alembic_version` check above; if the database was built from the SQL files, stamp
`a7c3e91d5b02` first). Verify read-only: `SELECT id FROM agents WHERE id = 'chris';`
returns no rows and `GET /chris/agents` does not list Chris. Do not delete the row by
hand. To preview the SQL for PostgreSQL:
`alembic upgrade a7c3e91d5b02:d4f1b8a2c967 --sql`.

Both `backend/app/db/seed_agents.py` and `docs/db_docs/seed_agents.sql` insert
missing default agents as `approved` and leave existing records entirely unchanged.
Re-running either seed preserves status, activity, tier, role, featured settings,
review history, timestamps, and edited agent metadata (including URLs). Changes to
existing agents require an explicit update rather than rerunning the seed.

## Integrated selection workflow

| Hop | Request | Reply |
|---|---|---|
| Frontend -> Chat (`POST /chat/message`) | Question, history, optional chat ID and guest session | Readable text and structured `routing` |
| Chat -> Chris (A2A) | Question; history in `metadata.history` | Text plus `openbeavs.chris.routing.v1` data |
| Chris -> registry (A2A) | Question; history in a data part | Compact text JSON: selected ID/endpoint or `"none"`; coded error on failure |

The [registry contract](#the-contract-chris-builds-against) defines the exact wire
shapes and registry errors. Chris forwards only the chosen ID to Chat; Chat looks up
the name/description for display. Confidence and reason remain inside the registry.
Each receiver validates the contract rather than inferring a result from prose.

The frontend uses normal message bubbles: for example, "I found the Math Expert
specialist for your question." Selection details are logged, not shown as debug cards.
The expert is not called yet. Backend failure codes, sources and retry diagnostics
remain in service terminal logs. They are absent from Chris-to-Chat routing payloads
and browser schemas.

`CHRIS_SELECTION_ONLY=false` (the default) uses Gemini on no-match or registry failure.
`true` disables fallback for diagnostics: no-match is plain text, failures are failed
A2A calls. If Chris cannot answer, Chat returns a generic HTTP 503 notice and saves no
turn. The frontend keeps this notice outside the conversation and excludes failed
turns from subsequent history. Each service configures INFO-level console logging at
its entrypoint, so selection details and failures can be inspected in its terminal.

### Timeouts and bounded history

| Layer | Setting | Value | Why this value |
|---|---|---|---|
| Registry: wait for a model slot | `REGISTRY_MODEL_QUEUE_SECONDS` | 2 s | refuse quickly when busy |
| Registry: one Gemini request | `REGISTRY_MODEL_TIMEOUT_SECONDS` | 8 s | bound the complete model request |
| Registry worst case | | about 10 s + database time | queue + model |
| Chris -> registry (discovery + selection) | `REGISTRY_A2A_TIMEOUT_SECONDS` | 14 s | above the registry worst case |
| Chat -> Chris | `CHRIS_A2A_TIMEOUT_SECONDS` | 35 s | allows registry 14 s plus optional fallback 15 s and response overhead |
| Browser | fixed in `api.ts` / `conversation.ts` | 90 s | unchanged |

The 8-second model deadline plus 2-second queue leaves time within Chris's
14-second overall registry deadline for discovery/database work. Optional fallback
has a separate 15-second deadline inside Chat's 35 seconds. Coordinate overrides;
there is no expert-call budget yet.

Chat queries only the six latest stored turns, restores their chronological order, and
bounds history before serializing either A2A hop (six turns, 1,000 UTF-8 bytes each).
Questions are limited to 4,000 UTF-8 bytes by the Chat API. This leaves room for JSON
escaping below the registry's 64 KiB body limit. A failed display-name lookup retains
the selected ID rather than discarding a successful selection.

Local A2A auth is disabled for this demonstration and refused outside the supported
local environment. Google verification has synthetic tests only; Chris does not attach
tokens yet. See [Authentication](#authentication) for registry A2A requirements.

## Local development setup

Use Python 3.12 and Node 22 or newer. No scratch-folder path is needed. The examples
use three terminals and a local SQLite database; do not use production credentials.
Keep both backend services running while using the browser.

### First-time setup

From the repository root, open PowerShell. These commands use a separate
`registry-demo.db` SQLite database so an existing local database stays untouched:

```powershell
cd backend
$env:DATABASE_URL='sqlite:///./registry-demo.db'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -r requirements-dev.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Edit the ignored `backend/.env` privately. Set `REGISTRY_MODEL` to your team's available Gemini model ID, and
`REGISTRY_GEMINI_API_KEY` to your own key. Never commit or share the key. Set
`REGISTRY_DEV_AUTH=true` only for this local SQLite setup. The example file configures
Gemini fallback; configure its own `CHRIS_MODEL` and `GEMINI_API_KEY`.
Existing environment files are deliberately preserved by this integration; check these
non-secret settings yourself if your file predates the runbook.

Initialize and seed that local database:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.db.seed_agents
# Optional extra choices for a selection demo; these are placeholders, not callable experts:
.\.venv\Scripts\python.exe scripts/seed_demo_agents.py
cd ../frontend
npm ci
```

### Terminal 1: registry (from backend/)

```powershell
$env:DATABASE_URL='sqlite:///./registry-demo.db'
$env:REGISTRY_PUBLIC_URL='http://127.0.0.1:8001'
$env:REGISTRY_A2A_AUTH='dev'
$env:REGISTRY_MODEL_QUEUE_SECONDS='2'
$env:REGISTRY_MODEL_TIMEOUT_SECONDS='8'
.\.venv\Scripts\python.exe -m uvicorn app.registry.a2a_app:create_standalone_app --factory --host 127.0.0.1 --port 8001
```

Check `http://127.0.0.1:8001/ready`; it should return 200. A 503 means a database,
auth, public URL, model or key configuration check failed. Readiness does not call
Gemini and cannot establish that the key/model is accepted by the provider.

### Terminal 2: Chat and Chris (from backend/)

```powershell
$env:DATABASE_URL='sqlite:///./registry-demo.db'
$env:REGISTRY_DEV_AUTH='true'
$env:REGISTRY_ADMIN_EMAILS='admin@example.test'
$env:CHRIS_PUBLIC_URL='http://127.0.0.1:8010'
$env:CHRIS_A2A_URL='http://127.0.0.1:8010/chris/a2a/'
$env:REGISTRY_A2A_URL='http://127.0.0.1:8001/a2a/registry'
$env:REGISTRY_A2A_TIMEOUT_SECONDS='14'
$env:CHRIS_A2A_TIMEOUT_SECONDS='35'
$env:CHRIS_SELECTION_ONLY='false'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

### Terminal 3: frontend (from frontend/)

```powershell
$env:BACKEND_ORIGIN='http://127.0.0.1:8010'
npm run dev
```

Open the Local URL printed by Vite in Chrome (normally `http://127.0.0.1:5173`).
Use plain `npm run dev`; the pipeline browser runner sets its own ports directly.

Try an OSU question, then a related follow-up in the same conversation. If you added
the demo agents, try `What is 15% of 240?`. Expect a plain acknowledgement naming
the selected specialist; expert dispatch is not implemented. The real model can choose differently; use the deterministic tests below to
verify the plumbing without Gemini credentials.

### Submit and review an expert agent

With Chat/Chris running on port 8010, open `http://127.0.0.1:8010/docs`, or use a
fourth PowerShell terminal. The headers below are synthetic local-development identities.
Use a reachable public HTTPS agent/card URL; loopback and private addresses remain
blocked by the registration safety checks.

```powershell
$headers = @{ 'X-User-Id'='registry-demo'; 'X-User-Email'='submitter@example.test' }
$cardUrl = Read-Host 'Public HTTPS agent or Agent Card URL'
$agent = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8010/registry/agents' -Headers $headers -ContentType 'application/json' -Body (@{ url=$cardUrl } | ConvertTo-Json)
$agent | Select-Object id, name, status, is_active
```

In default `auto` mode, a clean card becomes active and `provisional`; flagged cards
remain pending. An already registered card returns HTTP 409. To approve a pending
entry using the local admin configured in Terminal 2:

```powershell
$adminHeaders = @{ 'X-User-Id'='registry-admin'; 'X-User-Email'='admin@example.test' }
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8010/registry/agents/$($agent.id)/review" -Headers $adminHeaders -ContentType 'application/json' -Body (@{ action='approve' } | ConvertTo-Json)
Invoke-RestMethod -Uri 'http://127.0.0.1:8010/chat/agents'
```

Ask a question matching that expert in the frontend. Selection reads the agents table
on each request, so a newly eligible expert can be considered without restarting the
registry. For the full submission/review rules, see [How an agent gets in](#how-an-agent-gets-in).

## Workflow validation

From `backend/`:

```powershell
$env:PYTHON_DOTENV_DISABLED='1'
$env:DATABASE_URL='sqlite:///:memory:'
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

Use a separate terminal for tests so those environment overrides do not affect the
servers. From `frontend/`:

```powershell
npm run lint
npm run test
npm run build
npx playwright install chromium
npm run test:e2e
npm run test:pipeline
```

`test:pipeline` starts an isolated real Chat/Chris/registry stack with a scripted model,
a temporary database and no credentials, on ports 8100/8101 and frontend 5273.
Keep those ports free. It runs on Windows and Linux; `PIPELINE_PYTHON` may name a
backend Python executable explicitly. Otherwise it uses the local backend virtual
environment when available, or `python` from PATH. Set `PLAYWRIGHT_CHANNEL=msedge`
to use installed Edge instead of downloading Chromium. Both browser suites run in CI.

On Linux/macOS, use `.venv/bin/python` instead of `.venv\Scripts\python.exe`,
`export NAME=value` instead of PowerShell environment assignments, and `cp` for the
example file. The Python, npm and Alembic entry points are otherwise the same.

The backend suite covers registration/URL safety, card formats, review/auth guards,
selection and fresh eligibility, concurrency/deadlines, readiness, safe logs, capacity,
and migrations. Unit/integration and browser pipeline tests use a fake model and no
credentials. Live model requests separately verify provider configuration and example
choices; they are not a repeatable accuracy benchmark.

## Not done yet

- **Expert invocation.** Chris receives a selected expert but does not call it; no
  specialist answer or expert-call timeout is implemented yet.
- **Deployed A2A authentication.** The registry can verify Google ID tokens, but Chris
  does not fetch/attach them. Cloud Run/IAM and Cloud SQL have not been verified.
- **No real authentication, so no production approval** (see above).
- **No DNS-rebinding protection** and no re-validation of stored endpoints (see Security).
- **Cards are copied once.** There is no refresh when an agent changes its card.
- **The same agent can be registered twice under different hostnames.** Uniqueness is
  on the card URL, so Cloud Run's two hostnames for one service count as two agents.
- **No pagination.**
- `docs/db_docs/database-erd.png` was not regenerated; `database-erd.mmd` and the
  diagram in `database-architecture.md` are current.
