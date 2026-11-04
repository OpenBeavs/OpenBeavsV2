# Agent Registry

Registry management is how an A2A agent gets into OpenBeavs and becomes eligible
for the frontend directory and future execution. An agent is submitted by URL and
must pass a set of automated checks.
In the default **auto** mode an agent that passes goes live as `provisional`;
in **manual** mode it waits for an admin to approve it.

It is a module of the backend (`backend/app/registry/`) that writes to the unified
`agents` table described in `docs/db_docs/database-architecture.md`. There is no
separate management database. Chris calls a separately configured A2A registry
selection service; this module does not implement that service or choose agents
for individual messages.

## How an agent gets in

```
submit URL -> safe-address check -> fetch + clean + validate card -> wording check -> decision
                                                                                        |
        auto mode (default): clean card -> "provisional" (live)   flagged card -> "pending"
        manual mode:         every card -> "pending" (waits for an admin)
                                                                                        |
                              directory eligibility: "approved" or "provisional"
```

1. **Submit.** `POST /registry/agents` with `{"url": "..."}`. Nothing else is accepted.
2. **Fetch.** The hub requests the agent's discovery card (`/.well-known/agent.json`)
   after checking the address is safe (see Security). The card is validated.
3. **Decision** (`REGISTRY_APPROVAL_MODE`, see Approval mode below).
   - **auto** (default): a card that passed every check, with no warning flag, is
     stored as `provisional` and active, making it eligible for the directory. It is
     recorded as reviewed by `system:auto`. A card flagged for steering wording is
     held as `pending`.
   - **manual**: the agent is stored with `status = pending` and `is_active = false`.
     Only the submitter and admins can see it; it is excluded from the directory.
4. **Review.** An admin calls `POST /registry/agents/{id}/review`. `approve` and
   `provisional` make the agent active and visible; `revoke` and `reject` make it
   inactive and hidden. The reviewer and time are recorded. This still works on
   auto-approved agents, so any of them can be revoked.
5. **Directory eligibility.** Chat lists only active agents whose status is
   `approved` or `provisional`, with public access and no required role
   (`service.routable_agents`). This is a conservative filter, not a new tier system.

## Statuses

| Status | Eligible review status | Visible to other users | Meaning |
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

## Endpoints

| Method and path | Who | What |
|---|---|---|
| `POST /registry/agents` | signed-in user | Submit by URL. 201 with the pending entry; 400 for an unsafe or invalid card; 409 if the card URL is already registered; 422 if the body has anything but `url` |
| `GET /registry/agents` | signed-in user | List what the caller may see. Optional `?status=` |
| `GET /registry/agents/{id}` | signed-in user | One entry, or 404 if it does not exist or is not visible |
| `POST /registry/agents/{id}/review` | admin | Body: `action` (`approve`, `provisional`, `revoke`, `reject`), optional `note`, `trust_tier`, `required_role`, `is_featured` |

Submitter and review details (`submitted_by`, `reviewed_by`, `reviewed_at`,
`review_note`) are returned only to admins and to the submitter.

The chat directory, `GET /chat/agents`, returns the routable agents. This database
list is separate from the A2A registry selection service that Chris calls through
`REGISTRY_A2A_URL`; the management routes in this module do not implement selection.

## Where each stored field comes from

| Field | Source |
|---|---|
| `id` | Generated by the hub (UUID). Not read from the card |
| `name`, `description`, `skills`, `capabilities` | The agent card, validated (name at most 128 characters, description at most 4000, at most 50 skills) |
| `card_url` | The address the hub fetched. A submitted URL without `/.well-known/` becomes `<scheme>://<host>/.well-known/agent.json`; any path on it is dropped, so paste the full card URL for an agent hosted under a path |
| `endpoint_url` | The card's required absolute `url`, checked with the safe-URL rules. Its path and query are preserved; a missing or invalid endpoint rejects the submission rather than guessing from the discovery address |
| `trust_tier`, `is_featured`, `status`, `is_active` | Set by the server or by an admin review, never by the submitter |
| `submitted_by` | The caller's email |

## Security

- **Safe URLs.** The hub fetches submitted URLs from its own server, so it refuses
  anything that could reach internal systems: plain `http` (unless
  `REGISTRY_ALLOW_HTTP`), credentials in the URL, `localhost`,
  `metadata.google.internal`, and any host resolving to a loopback, private,
  link-local (including the cloud metadata address `169.254.169.254`), multicast,
  reserved or carrier-grade-NAT address, IPv4 or IPv6.
- **Advertised endpoint.** The card must include a non-empty absolute `url`. The registry independently checks its scheme, credentials, hostname, and resolved addresses, including when it differs from the card host. Paths such as `/rpc`, trailing slashes, and query strings are preserved. Relative URLs, fragments, backslashes, and embedded whitespace/control characters are rejected. `REGISTRY_ALLOW_HTTP` applies to both addresses but never permits private destinations. This is submission-time validation, not proof of endpoint availability; the existing DNS-rebinding limitation still applies. Existing database records are not rewritten.
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

- Registry management cannot trigger a card fetch in production: submission needs
  authentication, which is not implemented, so the registry routes answer 501 there
  (see Authentication). This is a property of the current MVP configuration, not a
  permanent guarantee. Chris's separate registry-selection client can still fetch
  the card of its operator-configured A2A registry service.
- Nothing calls a selected specialist endpoint yet. Chris now uses the official
  A2A SDK to contact an operator-configured registry service, but returns a selected
  specialist's JSON without invoking it. Stored specialist endpoints are validated
  only when submitted. **Before any code calls
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

Chris is the orchestrator. His discovery card
(`GET /chris/a2a/.well-known/agent-card.json`) is generated by ADK, and he has no
row in `agents`. The old handwritten `/chris/.well-known/agent.json` route is gone.
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
returns no rows and `GET /chat/agents` does not list Chris. Do not delete the row by
hand. To preview the SQL for PostgreSQL:
`alembic upgrade a7c3e91d5b02:d4f1b8a2c967 --sql`.

Both `backend/app/db/seed_agents.py` and `docs/db_docs/seed_agents.sql` insert
missing default agents as `approved` and leave existing records entirely unchanged.
Re-running either seed preserves status, activity, tier, role, featured settings,
review history, timestamps, and edited agent metadata (including URLs). Changes to
existing agents require an explicit update rather than rerunning the seed.

## Running it locally

```powershell
cd backend
python -m venv .venv ; .venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" httpx "sqlalchemy>=2" alembic python-dotenv psycopg2-binary pytest ruff
$env:DATABASE_URL = "sqlite:///./registry-local.db"
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m app.db.seed_agents
$env:REGISTRY_DEV_AUTH = "true"; $env:REGISTRY_ADMIN_EMAILS = "admin@example.test"
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8100
```

Then, with any HTTP client, submit as a user and approve as the admin:

```
POST http://127.0.0.1:8100/registry/agents
  X-User-Id: alice            X-User-Email: alice@example.test
  {"url": "https://<agent-host>"}

POST http://127.0.0.1:8100/registry/agents/<id>/review
  X-User-Id: admin            X-User-Email: admin@example.test
  {"action": "approve"}

GET  http://127.0.0.1:8100/chat/agents
```

## Tests

```powershell
cd backend
.venv\Scripts\python.exe -m pytest        # all suites
.venv\Scripts\python.exe -m ruff check .
```

`backend/tests/registry/` covers the safe-URL check, card fetching and validation
(including compression, size, deadline and metadata cleaning), the development-auth
guard, the API (submission, visibility, review, authentication), the chat directory's eligibility filter,
and the migrations (existing agents stay routable, Chris removal with and without
foreign-key enforcement, round trip, and valid Postgres SQL).

## Not done yet

- **Specialist execution is not implemented.** Chris calls a configured registry
  agent over A2A, validates its selection, and returns selected-agent JSON as text.
  No match or a failed selection triggers Gemini. This repo's registry management
  API is not the A2A selection agent. See [Chris's contract](chris.md).
- **A2A service authentication is not implemented.** The Chris and registry A2A
  clients do not attach service identity tokens; registry management's development
  user headers are a different mechanism.
- **No real authentication, so no production approval** (see above).
- **No DNS-rebinding protection** and no re-validation of stored endpoints (see Security).
- **Cards are copied once.** There is no refresh when an agent changes its card.
- **The same agent can be registered twice under different hostnames.** Uniqueness is
  on the card URL, so Cloud Run's two hostnames for one service count as two agents.
- **No pagination.**
- `docs/db_docs/database-erd.png` was not regenerated; `database-erd.mmd` and the
  diagram in `database-architecture.md` are current.
