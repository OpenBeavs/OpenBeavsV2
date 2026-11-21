# RFC: Database Simplification — Migrating OpenBeavs to a Lean 5-Table Schema
**Project 39: OpenBeavs (GENESIS-AI-Hub)**  
**Author:** Dean R Leon `<leond@oregonstate.edu>`  

| Field | Value |
| :--- | :--- |
| **Author** | Dean R Leon (Quality Owner) |
| **Date** | 2026-10-23 (revised 2026-11-20) |
| **Status** | Accepted (Option A) |
| **Decision Date** | 2026-10-23 |
| **Deciders** | Faith Nambasa, Jiya Pradhan, Dean R Leon, Pedro P Blanco Jaramillo, John V. Sweet |
| **Superseded By** | N/A |

---

## Problem and Context

OpenBeavs (GENESIS-AI-Hub) connects Oregon State University students and faculty to autonomous AI agents via the Agent-to-Agent (A2A) protocol, a JSON-RPC 2.0 standard in which each agent publishes a discovery card at `/.well-known/agent.json` describing its endpoint and capabilities. Our "Chris" orchestrator reads those cards and routes each user query to the best-matching agent. When our team inherited v1, we received an Open WebUI fork built as a personal ChatGPT clone with channels, Python valves, and local vector stores.

Consequently, the legacy database contains over twenty tables (`channels`, `folders`, `prompts`, `tools`, `memories`, `documents`, `knowledge`, and duplicate agent schemas). Roughly 80% of these tables serve features outside our scope: downstream campus agents manage their own retrieval, embeddings, and tools. OpenBeavs only needs to register agents, route queries through Chris, track sessions, and triage feedback.

Operationally, v1 runs dual ORMs (Peewee and SQLAlchemy) joined by regex connection hacks at boot, which cause connection pool exhaustion and 12-to-18-second Cloud Run cold starts. Conversations are also stored as monolithic JSON blobs: appending one turn requires reading, mutating, and rewriting the entire multi-turn history.

We must decide this in Week 4 of Fall term, as we architect OpenBeavs v2. If we do nothing, incoming features (live agent discovery, OSU Microsoft SSO, and session persistence) will couple permanently to this fragile schema, and every later feature will inherit the cost. Per Jeff Bezos's 2015 Amazon Shareholder Letter, this is a Type 1 decision: hard to reverse once other work builds on it.

---

## Options

### Option A: Clean-Slate Simplification to a 5-Table Schema (SQLAlchemy 2.0 + Alembic)
Rebuild the persistence layer around five relational tables:
1. `agents`: A2A discovery cards, endpoints, protocol capabilities, and trust tiers (`public`, `auth`, `privileged`).
2. `users`: OIDC identity claims (ONID, email, role) with no local passwords.
3. `chats`: conversation sessions, origin domains, and a 24-hour guest expiration TTL.
4. `messages`: append-only relational message turns enabling streaming and envelope encryption.
5. `tickets`: user feedback, routing errors, and bug reports.

This standardizes on SQLAlchemy 2.0 with Alembic and eliminates Peewee, ChromaDB, and monolithic JSON blobs in one step.
- **Costs:** Engineering effort in Weeks 4–5 to draft declarative models, write migrations, and update FastAPI routes; the legacy UI breaks until a serializer layer is in place; any v1 data we want to keep needs a one-time migration script.
- **Winning condition:** The team commits to OpenBeavs as an A2A router and prioritizes fast cold starts and maintainability over backwards compatibility with Open WebUI widgets.

### Option B: Incremental Pruning (Keep Open WebUI's Backend, Logically Disable Tables)
Keep Open WebUI's backend and migration graph, but deprecate unused tables (`channels`, `memories`, `valves`) by removing their API routes while leaving the tables in place.
- **Costs:** Dual ORMs remain linked at startup; connection leaks and slow cold starts persist; message turns stay trapped in monolithic JSON blobs in `chats.py`; dead tables clutter Cloud SQL.
- **Winning condition:** The team requires bi-directional sync with upstream Open WebUI releases, or lacks the bandwidth to refactor backend endpoints this term.

### Option C: Parallel Schema with Feature-by-Feature Retirement (Strangler Pattern)
Create the five new tables alongside the legacy schema, in the same Cloud SQL instance, managed only by SQLAlchemy 2.0 and Alembic. Every new v2 feature (agent discovery, SSO, session persistence) is built on the new tables from day one. Legacy tables are retired one feature at a time, as each legacy route is replaced, until the legacy tables and Peewee can be dropped. This applies the strangler fig pattern to a database.
- **Costs:** Peewee, the regex connection hacks, and the legacy models stay in the boot path until the final retirement step, so cold-start and connection-pool problems persist for most of the term. The two schemas must be kept consistent during the transition (for example, a user existing in both `user` and `users`), which adds dual-write or sync code that is itself a source of bugs. The cleanup step can slip and never happen.
- **Winning condition:** v1 has live users or data that must keep working throughout the transition, or the team cannot pause legacy feature work while the new layer is built.

### Option D: Do Nothing (Maintain 20+ Inherited Tables with Dual ORMs and Monolithic JSON Storage)
Develop OpenBeavs v2 directly on the inherited v1 database layer without modifications.
- **Costs:** Technical debt compounds; regex boot hacks cause connection exhaustion; legacy `passlib` bcrypt dependencies trigger security flags; monolithic JSON updates degrade I/O linearly with conversation length.
- **Winning condition:** OpenBeavs abandons the decentralized A2A hub architecture and becomes a local ChatGPT/Ollama-style web interface.

---

## Analysis

| Dimension | A: Clean Slate | B: Incremental Pruning | C: Parallel + Retire | D: Do Nothing |
| :--- | :--- | :--- | :--- | :--- |
| **Performance** | O(1) turn append; cold start target <= 2.0s | O(N) turn rewrite; cold start est. 8–10s | O(1) append for new features; legacy cold start until final retirement | O(N) rewrite; cold start 12–18s (measured) |
| **Complexity** | One ORM; ~470 lines across five model files (measured) | Dual ORMs; high debt | Dual ORMs plus sync code during transition; one ORM at the end | Dual ORMs; 20+ unused tables; ~1,800 LOC |
| **Migration risk** | High up front, short window | Low | Lowest per step, longest window | None now, compounding later |
| **Security and privacy** | Native OSU SSO; `expires_at` column for guest TTL; encryption-ready columns | Legacy password tables remain | Passwords tables remain until retired | `passlib` bcrypt issues; coarse blob encryption |
| **Operational cost** | Smallest Cloud SQL footprint (est. ~$15/mo) | Moderate (est. ~$35/mo) | Legacy-sized footprint until retirement | Highest memory overhead |

*Figures marked "est." and the targets in the Option A column are projections, not measurements; the Verification Plan is how we confirm them.*

### Performance
In legacy v1 (`back/models/chats.py`), chat turns live in one JSON field. Appending turn N means reading, deserializing, mutating, and rewriting the entire history, so transfer per turn grows with N. In Options A and C, messages are child rows linked to `chats.id`, so appends are constant-time. The cold-start benefit differs sharply, though. Cloud Run logs (`docs/CLOUD_RUN_OPERATIONS.md`) show that booting Open WebUI's 20+ models, dual ORMs, and vector stores takes 12–18 seconds. Only Option A removes that boot work immediately. Under Option C the legacy models still load at startup until the last one is retired, so the cold-start gain arrives at the end of the transition rather than the beginning.

### Complexity and Maintainability
Legacy authentication uses Peewee while agent registration uses SQLAlchemy. Running two migration engines requires regex URL sanitizers in startup scripts (`database/connect_cloud_run_to_sql.sh`). Fowler and Sadalage's *Evolutionary Database Design* argues that schemas should change in small, continuously verified steps, which favors Option C's incremental approach in principle. In our case, however, the schema being replaced is not a slightly wrong model of our domain; it models a different product. Consolidating into five models cuts schema code from 19 files and about 1,800 boilerplate lines to five model files totaling about 470 typed, documented lines in the v2 repository, and Option A achieves that in one step rather than across many.

### Security, Privacy, and Cost
Legacy Open WebUI stores local bcrypt hashes through `passlib`, which has compatibility problems with newer bcrypt versions (`database/BCRYPT_BUG_FIX.md`). Options A and C (once complete) delegate authentication to OSU Microsoft SSO (Entra ID OIDC) and store only verified ONID identifiers, emails, and roles. Option C keeps the password tables in place until the auth feature is retired, which prolongs exposure. Option A's schema also carries an `expires_at` column for 24-hour guest-chat expiry and key-reference columns (`encrypted_dek`, `kms_key_ref`) for envelope encryption with Google Cloud KMS; the purge job and key wrapping are not yet implemented, so these are capabilities the schema enables rather than behavior we have shipped. Removing unused tables lowers Cloud SQL memory pressure, which should allow a shared micro tier.

### Reassessing Option A Against Option C
Option C is a credible and, for many teams, the safer choice, and it beats Option A on one axis: it never leaves the product broken. Three facts about our situation shift the balance back to A:
1. **There is little legacy behavior to preserve.** The legacy features we would retire gradually (channels, memories, local knowledge bases) are ones we are deliberately not offering in v2, so there is no feature-by-feature replacement to stage. Most of the "retire one feature at a time" steps would be plain deletions.
2. **The expensive problem is startup, and C defers it.** The cold-start and connection-pool failures come from the dual-ORM boot path. Option C keeps that path alive until the last step, so the problem we most want to fix remains in the demo environment for most of the term.
3. **Sync code is new risk.** During the transition, identity and session data would be needed in both schemas, adding code whose only purpose is to be deleted.

Option C would become the better choice if the sponsor confirms that v1 has production users or conversation data that must remain available throughout the term, or if the team cannot absorb the Weeks 4–5 refactor. We have not confirmed either condition, so Option A stands, with a narrower margin than the first draft implied. A scoped one-step migration script for any v1 data that must survive covers part of Option C's advantage.

### Uncertainties
The main technical uncertainty is frontend compatibility: the legacy SvelteKit UI expects Open WebUI's nested chat JSON. Option A addresses this with lightweight Pydantic response serializers in FastAPI that assemble relational `messages` rows into that shape until the v2 frontend is finalized. A second uncertainty is whether the cost and cold-start figures above hold in practice; the gates below test that.

---

## Recommendation and Verification Plan

We recommend **Option A: Clean-Slate Simplification to a 5-Table Schema**. It removes dual-ORM debt in one step, should cut cold starts substantially, aligns the data model with the A2A protocol, and gives v2 features a secure, maintainable foundation. The team has voted to adopt Option A. We would revisit Option C only if the conditions named above turn out to hold.

### Verification Plan and Acceptance Criteria
The decision is validated against five gates; the first four are automated and the fifth is human.
1. **Schema integrity and test coverage (Week 5):** Pytest suites (`tests/test_models.py`, `tests/test_db.py`) must pass 100% in CI, asserting relational integrity and `ON DELETE CASCADE` from `chats` to `messages`.
2. **A2A orchestration integration (Week 6):** Chris must query live rows from `agents` rather than mock stubs (`tests/test_chris_db.py`), and `POST /chris/message` must persist turns into `messages` with p95 turn latency under 50 ms.
3. **Cloud Run cold start (Week 7 TA demo):** Measure container startup in Google Cloud Logging. Acceptance: time to a healthy `GET /health` is <= 2.0 seconds, down from 12–18 seconds in v1.
4. **Migration round-trip:** Alembic must run `upgrade head`, `downgrade base`, and `upgrade head` again against both SQLite and Cloud SQL PostgreSQL with zero errors.
5. **Independent human review (before merge, Week 5):** A teammate who did not write or prompt for the code reviews the schema, the generated DDL, and the tests. The reviewer must confirm that each test would fail if the behavior it checks were broken; as a spot check, they deliberately break one cascade rule and one foreign key and confirm CI goes red. The schema and the verification plan are also walked through with the full team and sponsor, so that AI-generated models and AI-written tests are not validated only by the tooling that produced them.

---

## Constraints

- **Licensing:** Both Open WebUI and OpenBeavs use the permissive MIT License; there is no copyleft (GPL) code. This keeps Options A, B, and C open and means reusing legacy code needs only license-notice retention.
- **Data governance and FERPA:** Under OSU data protection policies, no student educational records or permanent PII are retained; user records are limited to SSO directory claims. This is why `users` holds no passwords and why guest chats expire after 24 hours.
- **Confidentiality boundary:** Project 39 operates under an open-source agreement with sponsor John V. Sweet (OSU). Per Team Charter Section 5, connection strings, service account keys, and KMS secrets live in Google Cloud Secret Manager and untracked `.env` files, and are excluded from version control and from external AI prompt contexts. This also governs what may be pasted into AI tools during this work.

---

## Delegation and Validation

- **What was handed to AI tools:** Generative AI (Gemini 3.8 Flash) scanned the 19 legacy model files in `OpenBeavs/front/backend/open_webui/models/`, identified redundant tables, drafted initial SQLAlchemy 2.0 models (`Agent`, `User`, `Chat`, `Message`, `Ticket`), and drafted structural sections of this RFC. In the revision, Claude (Anthropic) was used to draft the Option C analysis and tighten wording in response to peer review.
- **What checks made that reasonable:** The repository enforces deterministic gates: Pytest, Ruff linting and formatting through pre-commit hooks, and isolated SQLite testing before any migration touches Cloud SQL. AI-generated code was not merged until all tests passed. Because tests written or approved by the same AI can share its blind spots, gate 5 adds a human reviewer who checks that tests can actually fail.
- **Where I stopped and validated the result myself:** As Quality Owner, I inspected the generated SQL DDL via `alembic upgrade --sql` to verify indexes and cascade behavior, and manually checked connection-string parsing in `session.py` to confirm that the legacy Peewee hacks were removed. On Wednesday, October 21, 2026, I presented the 5-table schema and ERD to sponsor John V. Sweet, who confirmed it satisfies A2A discovery-card and routing requirements. I compared this RFC's claims against the `dev` branch of the v2 repository. That check found that the five models total about 470 lines, not the roughly 250 the first draft claimed, and that guest-chat TTL purging and KMS key wrapping exist only as schema columns, so I corrected all three statements. It also confirmed that the v2 backend contains no Peewee code and that `POST /message` on the Chris router and the `/health` endpoint exist.

---

## Decision

**Status:** Accepted  
**Decision:** The team voted to adopt **Option A: Clean-Slate Simplification to a 5-Table Schema (SQLAlchemy 2.0 + Alembic)**.  
**Chair:** Dean R Leon (Quality Owner)  
**Decision Date:** 2026-10-23  
*(The team voted on 2026-10-23, before peer review. Peer review added Option C and the reassessment of Option A as documented alternatives; it did not change the outcome. Option C remains the documented alternative, to be revisited if the sponsor confirms that v1 data or users must stay live during the transition. Status and Decision are updated here if that changes.)*

---

## References

1. Bezos, J. (2015). *2015 Letter to Shareholders*. Amazon.com, Inc. (Type 1 and Type 2 decisions.)
2. Sadalage, P. and Fowler, M. *Evolutionary Database Design*. martinfowler.com/articles/evodb.html
3. Fowler, M. *Strangler Fig Application*. martinfowler.com/bliki/StranglerFigApplication.html
4. SQLAlchemy 2.0 Documentation and Alembic Documentation. sqlalchemy.org, alembic.sqlalchemy.org
5. Project repository documents: `docs/CLOUD_RUN_OPERATIONS.md`, `database/BCRYPT_BUG_FIX.md`, `database/connect_cloud_run_to_sql.sh`, `back/models/chats.py`; Team Charter, Section 5.