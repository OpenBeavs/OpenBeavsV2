# OpenBeavs v2

The OSU AI hub prototype, with a standalone Chris frontend and FastAPI backend.

- `frontend/`: Svelte chat interface and read-only registered-agent directory.
- `backend/`: chat REST API and persistence, Chris's ADK/A2A agent, and registry management.
- `docs/`: API, frontend setup, and database documentation.

Start with [local setup and frontend integration](docs/frontend.md), then see
[Chris's API](docs/chris.md). The frontend runs independently of the original
Open WebUI backend. Chat calls Chris over A2A; Chris always asks the configured
registry agent and uses Gemini when selection fails or returns no match. A selected
specialist's JSON is currently returned without invoking it. Verified SSO and
service-to-service authentication remain future work.

For Agent Registry behavior, local setup, and testing, see [Agent Registry documentation](docs/registry.md).

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before making
changes. AI-generated changes remain unstaged and uncommitted for human review.
