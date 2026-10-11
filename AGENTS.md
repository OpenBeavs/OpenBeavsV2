# AGENTS.md

Instructions for AI coding agents working in the OpenBeavs v2 repository. OpenBeavs is the OSU AI agent platform: a hub that registers, secures, and relays messages to A2A agents. Read this file fully before making changes.

##  Core Principles & Persona

All agents in this repository operate under a shared set of baseline instructions:

* **Direct & Concise:** Provide factual answers without unnecessary pleasantries or conversational filler.
* **Deterministic Tools:** Rely heavily on validated tool execution rather than generalized LLM assumptions.
* **Error Handling:** Gracefully log failures and notify the orchestrator when a task cannot be completed.

##  Git rules (hard constraints)

- **Never commit.** Do not run `git commit`, `git commit --amend`, or any command that creates a commit.
- Do not push, merge, rebase, tag, force-push, or open pull requests.
- Do not stage files (`git add`) unless the user explicitly asks.
- Leave all changes in the working tree. When a task is done, summarize what changed (files and why) and let the human review, stage, and commit.
- Read-only git commands are fine: `git status`, `git diff`, `git log`, `git blame`.
- If a task seems to require a commit, stop and ask.

## Project overview

- **UI:** SvelteKit with Svelte.
- **Hub backend:** Python, FastAPI, SQLAlchemy with Alembic migrations.
- **Agents:** Standalone A2A services that the hub talks to over JSON-RPC (`message/send`).
- **Orchestrator ("Chris"):** Picks an installed agent for a message, calls it over A2A, or answers directly.

> Update the layout below as v2 takes shape. Keep it accurate (see "Documentation rules").

## Dev environment tips

- Check the folder you are in before running commands. UI and backend have separate toolchains and separate test runners.
- Use ripgrep or your editor's search to locate routers, models, and components instead of scanning with `ls`.
- Backend: use a virtual environment, and install dependencies from the backend's requirements file. Never install packages globally.
- UI: install with `npm install` from the UI folder, and use the lockfile that is committed.
- Configuration comes from environment variables. Read secrets from env or Secret Manager. Never hardcode a key, token, signing secret, or placeholder secret (for example `change-me`) in code, Dockerfiles, or CI config.

## Testing instructions

- Find the CI plan in `.github/workflows`. CI must run every test suite that ships to production, including the backend and the security tests. If you add a suite, make sure CI runs it.
- Backend: run `pytest` from the backend folder. Run the security tests too, and do not skip them. Lint with `ruff check .`.
- UI: run `npm run test` and `npm run lint` from the UI folder. Do not rely on `--passWithNoTests` to make a job pass.
- To focus on one backend test: `pytest -k "<test name>"`. For the UI: `npx vitest run -t "<test name>"`.
- Fix any test, lint, or type errors until the whole suite is green.
- After moving files or changing imports, run the linters again.
- Add or update tests for the code you change, even if nobody asked. Security-relevant changes need a test that fails without the fix.
- Do not mark a test as `xfail` or skip it to get green. Report it instead.
- If you could not run a test (missing dependency, no network), say so explicitly rather than implying it passed.

## Documentation rules

- **Any architectural change in the workflow must be followed by a documentation update in the same change set.** This includes new or removed services, changed request flows, new routers or route prefixes, auth or trust-tier changes, database or storage changes, new environment variables, and deployment changes.
- Update the relevant file in `docs/`.
- Docs must describe what the code does now, not what was planned. If you find a doc that disagrees with the code, flag it.
- The code is well documented, and it must stay that way. New modules, routers, and non-trivial functions get docstrings or comments that explain intent and constraints, not just restate the code.
- When removing a feature, remove its documentation too. Do not leave stale diagrams or route lists behind.

## Code style

- Python: follow ruff defaults. Type-hint public functions. Keep routers thin and put logic in `utils/` or models.
- Prefer small, reviewable changes. Do not refactor unrelated code in the same change.
- Do not add dependencies without saying why in your summary.

## PR instructions (for the human who commits)

Agents do not open PRs or commit. Prepare the work so the human can:

- Title format: `[<area>] <Title>` (for example `[backend] Enforce tier check on embed routes`).
- Before committing, run the backend `ruff check .` and `pytest`, and the UI `npm run lint` and `npm run test`.
- In your final summary, list changed files, tests run and their results, docs updated, and anything you could not verify.

## When something goes wrong

- Log the failure clearly, with the error and the step that failed.
- Notify the orchestrator or the user that the task could not be completed, and say what is blocked.
- Do not guess, fabricate output, or silently work around a failing tool. Ask for direction.
