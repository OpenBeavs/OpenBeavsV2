# AGENTS.md

Instructions for AI coding agents working in the OpenBeavs v2 repository. OpenBeavs is Oregon State University's federation of expert agents: a person asks a question in the OpenBeavs Chat System, which asks the Agent Registry which expert fits, carries the question to that expert over A2A, and returns the expert's answer under a badge naming it. Read this file fully before making changes.

`CLAUDE.md` holds only a pointer to this file, so that Claude Code, which reads `CLAUDE.md`, works from the same instructions as every other agent.

## Core Principles & Persona

All agents in this repository operate under a shared set of baseline instructions:

* **Direct & Concise:** Provide factual answers without unnecessary pleasantries or conversational filler.
* **Deterministic Tools:** Rely heavily on validated tool execution rather than generalized LLM assumptions.
* **Error Handling:** Gracefully log failures and notify the user, or the agent that delegated the task to you, when a task cannot be completed.

## Git rules (hard constraints)

- **Never commit.** Do not run `git commit`, `git commit --amend`, or any command that creates a commit.
- Do not push, merge, rebase, tag, force-push, or open pull requests.
- Do not stage files (`git add`) unless the user explicitly asks.
- Leave all changes in the working tree. When a task is done, summarize what changed (files and why) and let the human review, stage, and commit.
- Read-only git commands are fine: `git status`, `git diff`, `git log`, `git blame`.
- If a task seems to require a commit, stop and ask.

## AI usage & confidentiality rules

Guidelines for AI coding agents and contributors interacting with AI systems (e.g., ChatGPT, Claude, Antigravity, and repository agents):

- **What may be shared with AI:**
  - **Project Code:** All codebase source files, architecture diagrams, schemas, templates, tests, scripts, and documentation may be freely entered into AI tools for development, debugging, testing, refactoring, and code review.
- **Strict prohibitions (Secrets & Credentials):**
  - **Secrets such as environment variables (`.env`, `.env.local`), private API keys, signing secrets, service account credentials, and database passwords must NEVER be explicitly given or pasted into AI tools or committed to the repository.**
  - **OSU Credentials & Personal Info:** Never enter personal credentials, OSU student/staff account passwords, or Microsoft SSO authentication secrets/tokens into any AI tool.
  - AI agents must never log, echo, request, or persist real environment variable values or secrets. Use mock values, placeholders, or references to environment variable names only.
  - **The settings file:** One settings file, `.env`, sits at the repository root, and every service reads it. Never open, read, print, or commit it. `.env.example`, beside it, lists every setting by name, so refer to a setting by its name.
- **Maintainers' confidentiality responsibilities:**
  - The project's maintainers monitor agent configurations and AI tool workflows to enforce confidentiality compliance.
  - They ensure AI keys, API credits, and GCP credentials are secure (stored in Google Cloud Secret Manager or untracked local environment variables) and never exposed to AI contexts or public repositories.
  - They maintain this file and update its guidelines as project security policies evolve.
- **Human Review Mandate:**
  - All AI-generated code, tests, and documentation must be reviewed and verified by a human contributor before being staged, committed, or merged.

## Project overview

This repository holds two systems, the PostgreSQL resources they share, and the tests that run them together. Each system, component, and shared resource has a README in its own folder that describes it in full.

- **OpenBeavs Chat System** (`chat-system/`): the system people talk to, in three components.
  - **Web UI** (`chat-system/web-ui/`): SvelteKit with Svelte and TypeScript, built to static files that run in the browser.
  - **Application Services** (`chat-system/application-services/`, the package `application_services`): the chat API, turn handling, and sign-in, with no LLM. Python, FastAPI, SQLAlchemy with Alembic migrations.
  - **Conversation Agent** (`chat-system/conversation-agent/`, the package `conversation_agent`), which the code calls Chris: a Google ADK agent served over A2A. For each message it asks the Agent Registry which expert fits, calls that expert and relays its answer unchanged, or answers with Gemini when no expert fits or the selection fails.
- **Agent Registry** (`agent-registry/`, the package `agent_registry`): a separate system. It keeps the catalog of registered experts, selects one over A2A, and serves its own admin API. Python, FastAPI, SQLAlchemy with Alembic migrations.
- **Shared PostgreSQL resources** (`shared-resources/postgres/`): `owners.sql`, which gives each owner of data its own schema and login on one server.
- **End-to-end tests** (`tests/end-to-end/`): the tests that run more than one package together, and the scripted-model stack that the browser pipeline test starts.
- **Documentation** (`docs/`): design, requirements, risks, and database documentation, with the RFCs in `docs/RFCs/`.
- **Experts:** standalone A2A services that the Conversation Agent calls over JSON-RPC at the endpoint the Registry returns. Each expert lives in its own repository, and this repository holds no expert code.

At the repository root, `start-dev.py` and `start-dev-mac.sh` start every service, the `Makefile` and `scripts/dev.py` give the common commands short names, and `.github/workflows/checks.yml` is the CI plan.

Keep this overview accurate as the tree changes (see "Documentation rules").

### How the system works today

- The Agent Registry, the Conversation Agent, Application Services, and the Web UI each run as a process of their own. The Web UI calls Application Services over HTTP, Application Services calls the Conversation Agent over A2A, and the Conversation Agent calls the Registry, and then the expert, over A2A.
- Application Services stores no conversations. The browser keeps the conversation and sends its history with each message.
- Sign-in with Microsoft Entra ID is built as API routes in Application Services (`chat-system/application-services/application_services/auth/`). The Web UI has no sign-in screen yet, and chat works without signing in.
- The Registry's own process serves its admin API. Application Services serves no Registry route and reads no Registry table.
- The Conversation Agent runs only as its own process, and it has no database.
- Each owner of data, the Chat System and the Agent Registry, has its own database: locally a SQLite file in its own folder, and on PostgreSQL its own schema and login.

## Conventions of the tree

Each convention carries its reason, so that you can apply it to a case it does not name.

- **Each deployable package has its own `pyproject.toml`, environment, and lock file.** The packages are `agent-registry/`, `chat-system/application-services/`, and `chat-system/conversation-agent/`. Each has its own because a shared environment would let one package import another's code. Only `tests/end-to-end/` installs more than one, to test them together. A dependency goes into the package that uses it. `tests/end-to-end/uv.lock` records the dependencies of all three, so it changes whenever one of theirs does.
- **Each owner of data keeps its own migrations.** The Chat System's are in `chat-system/application-services/migrations/`, and the Registry's are in `agent-registry/migrations/`. No migration creates or alters another owner's tables, because on PostgreSQL each owner's login holds rights to its own schema alone. A row that refers to another owner's record stores that record's ID as plain text, with no foreign key.
- **Systems reach one another only over A2A.** A package never imports another package's code and never reads another owner's tables, so the messages are the whole contract between systems, and a system can be replaced or moved to its own repository with no change inside the others. The isolation test in each package (`tests/test_isolation.py`) fails when another package becomes importable there. Where two packages need the same logic, each keeps its own copy. Each service validates the others' messages exactly, so a change to a message's shape changes both ends in the same change set.
- **"frontend," "backend," and "infrastructure" never name a folder.** Each of those words names a layer, and a folder named for a layer collects components that follow different rules. Name a folder for the system or component it holds, so that the tree shows which code makes up each one.
- **An acronym keeps its capitals in a folder name,** as in `docs/RFCs/`, so that the folder reads the way the term is written everywhere else. `web-ui/` is the one exception, because "UI" is common enough to read as a word. A Python import folder uses the full word in lowercase, as in `database/`, because Python package names are lowercase.
- **Every path in code or configuration is relative to the repository's tree,** so that a clone works wherever it sits. Where an absolute path is unavoidable, it comes from an environment variable and never from a file git tracks.

## Dev environment tips

- Check the folder you are in before running commands. Each Python folder and the Web UI has its own toolchain, environment, and test runner. The commands in this file run from the repository root and enter each folder in a subshell.
- Use ripgrep or your editor's search to locate routers, models, and components instead of scanning with `ls`.
- Python: each folder uses its own virtual environment, which uv builds from the folder's `uv.lock`. Install with `uv sync --locked` from that folder, and run every tool through `uv run`. Never install packages globally.
- Web UI: install with `npm ci` from `chat-system/web-ui/`, which uses the lockfile that is committed.
- The root `README.md` gives the prerequisites, the whole install, the settings, the local databases, the launcher, and the ports, in that order. Its Windows section gives the differences for PowerShell.
- Configuration comes from environment variables. Read secrets from env or Secret Manager. Never hardcode a key, token, signing secret, or placeholder secret (for example `change-me`) in code, Dockerfiles, or CI config.

## Testing instructions

- Find the CI plan in `.github/workflows/checks.yml`. CI must run every test suite that ships to production, including every Python package's suite and the security tests. If you add a suite, make sure CI runs it.
- After every change, run the lint and the tests of every Python folder and of the Web UI, from the repository root. A change in one package can break `tests/end-to-end/`, which runs the three together.

  ```zsh
  (cd agent-registry && uv sync --locked && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
  (cd chat-system/conversation-agent && uv sync --locked && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 uv run pytest)
  (cd chat-system/application-services && uv sync --locked && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
  (cd tests/end-to-end && uv sync --locked && uv run ruff check . && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
  (cd chat-system/web-ui && npm run lint && npm run test)
  ```

  `uv sync --locked` brings the folder's environment to its lock file, and fails when `pyproject.toml` and `uv.lock` disagree. `PYTHON_DOTENV_DISABLED=1` keeps the tests from loading `.env`, and the in-memory database keeps them away from the local database files, as in CI. `npm run lint` runs ESLint and the Svelte and TypeScript checks.
- CI also runs the Web UI's production build, its browser tests, and the pipeline test, which starts the real Registry, Conversation Agent, and Application Services code with a scripted stand-in for Gemini and drives the Web UI in a browser. Run them before you report the whole suite green. The pipeline test starts the services from the environment of `tests/end-to-end/`, so that folder must be installed first, and both browser suites need the browser that `npx playwright install chromium` downloads once.

  ```zsh
  (cd chat-system/web-ui && npm run build && npm run test:e2e && npm run test:pipeline)
  ```

- The security tests run inside these suites: URL safety, caller authentication, sign-in, the isolation test in each package, and the database grants test. Run each suite whole, and do not skip them.
- The grants test (`tests/end-to-end/tests/test_database_grants.py`) proves that each owner's database login is refused the other owner's tables. It needs PostgreSQL and skips itself on SQLite, so the commands above report it as skipped. When a change touches a migration, a table, a database login, or `shared-resources/postgres/owners.sql`, run it, and the suites, against PostgreSQL by the "Test against it" section of `shared-resources/postgres/README.md`. In CI a skipped end-to-end test fails the job.
- Web UI: do not rely on `--passWithNoTests` to make a job pass.
- To focus on one Python test, from its folder: `uv run pytest -k "<test name>"`. For the Web UI, from `chat-system/web-ui/`: `npx vitest run -t "<test name>"`.
- From the repository root, `make lint` runs ruff in every Python folder and the Web UI's lint, and `make test` runs every Python suite and the Web UI's Vitest tests. `make test` sets neither variable above, so the packages load `.env` as they do when the services run; the commands above are the ones CI runs.
- Fix any test, lint, or type errors until the whole suite is green.
- After moving files or changing imports, run the linters again.
- Add or update tests for the code you change, even if nobody asked. Security-relevant changes need a test that fails without the fix.
- Do not mark a test as `xfail` or skip it to get green. Report it instead.
- If you could not run a test (missing dependency, no network), say so explicitly rather than implying it passed.

## Documentation rules

- **Any architectural change in the workflow must be followed by a documentation update in the same change set.** This includes new or removed services, changed request flows, new routers or route prefixes, auth or trust-tier changes, database or storage changes, new environment variables, and deployment changes.
- Update the document that describes what you changed. Each system, component, and shared resource is described by the README in its own folder. The root `README.md` covers setup, settings, commands, and deployment. `docs/` holds the design, the requirements, the risks, and the database documentation. A new environment variable also goes into `.env.example`, by name, with no secret value.
- Docs must describe what the code does now, not what was planned. If you find a doc that disagrees with the code, flag it.
- The RFCs in `docs/RFCs/` are dated records of decisions, so their text stays as written. Where a file an RFC cites has moved, add the new path in parentheses after the old one, as the existing notes do.
- The code is well documented, and it must stay that way. New modules, routers, and non-trivial functions get docstrings or comments that explain intent and constraints, not just restate the code.
- When removing a feature, remove its documentation too. Do not leave stale diagrams or route lists behind.

## Code style

- Python: follow ruff defaults. Type-hint public functions. Keep routers thin and put logic in the `service.py` beside the router, or in models.
- Prefer small, reviewable changes. Do not refactor unrelated code in the same change.
- Do not add dependencies without saying why in your summary.

## PR instructions (for the human who commits)

Agents do not open PRs or commit. Prepare the work so the human can:

- Title format: `[<area>] <Title>`, where the area is the system or component changed (for example `[agent-registry] Refuse card URLs that carry credentials`).
- Before committing, run the lint and the tests of each Python folder and of the Web UI, then the Web UI's build, browser tests, and pipeline test, by the commands under "Testing instructions."
- In your final summary, list changed files, tests run and their results, docs updated, and anything you could not verify.

`CONTRIBUTING.md` gives the commit message format, the pull request checklist, and the Definition of Done.

## When something goes wrong

- Log the failure clearly, with the error and the step that failed.
- Notify the user, or the agent that delegated the task to you, that the task could not be completed, and say what is blocked.
- Do not guess, fabricate output, or silently work around a failing tool. Ask for direction.
