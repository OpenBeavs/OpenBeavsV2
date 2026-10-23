# RFC: Database Simplification — Migrating OpenBeavs to a Lean 5-Table Schema
**Project 39: OpenBeavs (GENESIS-AI-Hub)**  
**Author:** Dean R Leon `<leond@oregonstate.edu>`  
**Date:** 2026-10-23  

| Field | Value |
| :--- | :--- |
| **Author** | Dean R Leon (Quality Owner) |
| **Date** | 2026-10-23 |
| **Status** | Proposed |
| **Decision Date** | (Pending Peer Review and Team Vote) |
| **Deciders** | Faith Nambasa, Jiya Pradhan, Dean R Leon, Pedro P Blanco Jaramillo, John V. Sweet |
| **Superseded By** | N/A |

---

## Problem and Context

OpenBeavs (GENESIS-AI-Hub) connects Oregon State University students and faculty to autonomous AI agents via the Agent-to-Agent (A2A) protocol (JSON-RPC 2.0 with `/.well-known/agent.json` discovery cards). When our team inherited v1, we received an Open WebUI fork built as a personal ChatGPT clone with channels, Python valves, and local vector stores.

Consequently, the legacy database contains over twenty tables (`channels`, `folders`, `prompts`, `tools`, `memories`, `documents`, `knowledge`, and duplicate agent schemas). Crucially, 80% of these tables serve features outside our scope: downstream campus agents manage their own retrieval, embeddings, and tools. OpenBeavs only needs to register agents, route queries via our "Chris" orchestrator, track sessions, and triage feedback.

Operationally, v1 runs dual ORMs (Peewee and SQLAlchemy) using regex connection hacks at boot, causing connection pool exhaustion and 12-to-18-second Cloud Run cold starts. Furthermore, conversations are stored as monolithic JSON blobs: appending one turn requires reading, mutating, and rewriting the entire multi-turn history.

We must decide this in Week 4 of Fall term as we architect OpenBeavs v2. If we do nothing, incoming features—live agent discovery, OSU Microsoft SSO, and session persistence—will permanently couple to this fragile schema. Per Jeff Bezos's 2015 Amazon Shareholder Letter, this is an irreversible Type 1 architectural decision.

---

## Options

### Option A: Clean-Slate Database Simplification to a 5-Table Schema (SQLAlchemy 2.0 + Alembic)
Rebuild the persistence layer around five core relational tables:
1. `agents`: A2A discovery cards, endpoints, protocol capabilities, and trust tiers (`public`, `auth`, `privileged`).
2. `users`: OIDC identity claims (ONID, email, role) with zero local passwords.
3. `chats`: Conversation sessions, origin domains, and 24-hour guest expiration TTL.
4. `messages`: Append-only relational message turns enabling streaming and envelope encryption.
5. `tickets`: User feedback, routing errors, and bug reports.

Standardizes on SQLAlchemy 2.0 with Alembic, eliminating Peewee, ChromaDB, and monolithic JSON blobs.
- **Costs:** Engineering effort in Weeks 4–5 to draft declarative models, write migrations, and update FastAPI routes.
- **Winning Condition:** The team commits to OpenBeavs as an A2A router, prioritizing sub-2s cold starts and maintainability over backwards compatibility with Open WebUI widgets.

### Option B: Incremental Pruning (Keep Open WebUI Backend, Logically Disable Tables)
Keep Open WebUI's backend and migration graph, but deprecate unused tables (`channels`, `memories`, `valves`) by removing API routes while leaving tables in place.
- **Costs:** Dual ORMs remain linked at startup; connection leaks and slow cold starts persist; message turns remain trapped inside monolithic JSON blobs in `chats.py`; dead tables clutter Cloud SQL.
- **Winning Condition:** The team requires bi-directional sync with upstream Open WebUI releases, or lacks bandwidth to refactor backend endpoints before Fall term ends.

### Option C: Do Nothing (Maintain 20+ Inherited Tables with Dual ORMs & Monolithic JSON Storage)
Continue developing OpenBeavs v2 directly on the inherited v1 database layer without modifications.
- **Costs:** Technical debt compounds; regex boot hacks cause connection exhaustion; legacy `passlib` bcrypt dependencies trigger security flags; monolithic JSON updates degrade I/O linearly with conversation length.
- **Winning Condition:** OpenBeavs abandons the decentralized A2A agent hub architecture to become a local ChatGPT/Ollama web interface with client-side code execution.

---

## Analysis

| Dimension | Option A: Clean 5-Table Schema (Recommended) | Option B: Incremental Pruning | Option C: Do Nothing |
| :--- | :--- | :--- | :--- |
| **Performance** | O(1) append turns; Cloud Run cold start <1.5s | O(N) turn rewriting; Cold start ~8–10s | O(N) turn rewriting; Cold start >12–18s |
| **Complexity** | Single ORM (SQLAlchemy 2.0); ~250 LOC models | Dual ORMs (Peewee + SQLAlchemy); high debt | Dual ORMs; 20+ unused tables; >1,800 LOC |
| **Security & Privacy** | Native OSU SSO; 24h guest TTL; granular crypto | Legacy password tables; coarse blob encryption | passlib bcrypt vulnerabilities; monolithic blobs |
| **Operational Cost** | Minimal Cloud SQL disk/RAM footprint (~$15/mo) | Moderate Cloud SQL footprint (~$35/mo) | High Cloud SQL & Cloud Run memory overhead |

### Performance
In legacy v1 (`back/models/chats.py`), chat turns are serialized in a monolithic JSON field. Appending turn N requires reading, deserializing, mutating, and rewriting the entire conversation history (O(N) transfer per turn). In Option A, messages are child rows in `messages` linked to `chats.id`, giving constant-time O(1) append latency. Additionally, Cloud Run logs (`docs/CLOUD_RUN_OPERATIONS.md`) show that booting Open WebUI's 20+ models, dual ORMs, and vector stores takes 12–18 seconds. Pruning to five SQLAlchemy 2.0 models slashes container startup to under 1.5 seconds.

### Complexity and Maintainability
Legacy v1 suffers from profound friction: authentication uses Peewee ORM, while agent registration uses SQLAlchemy. Maintaining two migration engines requires regex URL sanitizers in startup scripts (`database/connect_cloud_run_to_sql.sh`). Martin Fowler’s *Evolutionary Database Design* (2016) emphasizes that schemas must fit the bounded context. Consolidating into five models cuts schema code from 19 files and 1,800 boilerplate lines to 250 typed lines.

### Security, Privacy, and Cost
Legacy Open WebUI stores local bcrypt hashes using `passlib`, which has compatibility flaws with newer bcrypt versions (`database/BCRYPT_BUG_FIX.md`). Option A delegates authentication to OSU Microsoft SSO (Entra ID OIDC), storing only verified ONID identifiers, emails, and roles without local passwords. Option A enforces automated privacy: guest chats carry a 24-hour TTL index, and message turns support envelope encryption with Google Cloud KMS. Stripping unused tables lowers Cloud SQL memory pressure, enabling hosting on a shared micro tier ($15/month).

### Uncertainties
The primary technical uncertainty is frontend compatibility: the legacy SvelteKit UI expects Open WebUI's nested chat JSON. Option A resolves this by introducing lightweight Pydantic response serializers in FastAPI to transform relational `messages` rows until the v2 frontend is finalized.

---

## Recommendation and Verification Plan

We recommend **Option A: Clean-Slate Database Simplification to a 5-Table Schema**. It eliminates dual-ORM technical debt, slashes cold starts, aligns our data model with the A2A protocol, and establishes a secure, maintainable foundation.

### Verification Plan and Acceptance Criteria
The decision will be validated against four concrete gates:
1. **Schema Integrity and Test Coverage (Week 5):** Pytest test suites (`tests/test_models.py`, `tests/test_db.py`) must pass 100% in CI, asserting relational integrity and `ON DELETE CASCADE` from `chats` to `messages`.
2. **A2A Agent Orchestration Integration (Week 6):** Verify that "Chris" queries live entries from `agents` rather than mock stubs (`tests/test_chris_db.py`), and that `POST /chris/message` persists turns into `messages` with turn latency under 50ms (p95).
3. **Cloud Run Cold Start Metrics (Week 7 TA Demo):** Measure container cold starts in Google Cloud Logging. Acceptance criteria: Container startup to healthy `GET /health` must be <= 2.0 seconds (down from 12–18s in v1).
4. **Zero-Downtime Migration Verification:** Automated Alembic round-trips (`alembic upgrade head` then `alembic downgrade base` and re-upgrade) must execute against SQLite and Cloud SQL PostgreSQL with zero errors.

---

## Constraints

- **Licensing:** Both Open WebUI and OpenBeavs use the permissive MIT License with zero copyleft (GPL) code.
- **Data Governance and FERPA:** Under OSU data protection policies, no student educational records or permanent PII are retained; user records are limited to SSO directory claims.
- **Confidentiality Boundary:** Project 39 operates under an open-source agreement with sponsor John V. Sweet (OSU). Per Team Charter Section 5, database connection strings, Service Account keys, and KMS cryptographic secrets are managed via Google Cloud Secret Manager and local untracked `.env` files, strictly excluded from version control and external AI prompt contexts.

---

## Delegation and Validation

- **What was handed to AI tools:** Generative AI tools (Gemini 3.8 Flash) were delegated scanning the 19 legacy model files in `OpenBeavs/front/backend/open_webui/models/`, identifying redundant tables, drafting initial SQLAlchemy 2.0 models (`Agent`, `User`, `Chat`, `Message`, `Ticket`), and drafting structural sections of this RFC.
- **What checks made that reasonable:** The repository enforces deterministic verification gates: local unit testing with Pytest, Ruff linting/formatting via pre-commit hooks, and isolated SQLite testing before running migrations against Cloud SQL. AI models were not merged until all unit tests passed.
- **Where you stopped and validated the result yourself:** As Quality Owner, I personally inspected generated SQL DDL via `alembic upgrade --sql` to verify indexes and cascade behavior. I manually checked connection string parsing in `session.py` to confirm all legacy Peewee connection hacks were removed. During the sponsor check-in on Wednesday, October 21, 2026, I presented the proposed 5-table schema and ERD to sponsor John V. Sweet, who confirmed it satisfies A2A discovery card and routing requirements.

---

## Decision

**Status:** Proposed  
**Chair:** Dean R Leon (Quality Owner)  
**Date:** 2026-10-23  
*(Awaiting formal team vote following Week 5 peer review).*