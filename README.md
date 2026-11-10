# OpenBeavs v2

The OSU AI hub prototype, with a standalone Chris frontend and FastAPI backend.

- `frontend/`: Svelte chat interface and read-only registered-agent directory.
- `backend/`: chat REST API and persistence, Chris's ADK/A2A agent, and registry management.
- `docs/`: API, frontend setup, and database documentation.

Start with the [registry setup guide](docs/registry.md#local-development-setup), then see
[Chris's API](docs/chris.md). Chat calls Chris over A2A; Chris asks the standalone
registry to select an expert. By default the frontend shows the selection, no match,
or a coded error. Set `CHRIS_SELECTION_ONLY=false` to enable Gemini fallback for no
match or registry failures. No selected expert is invoked yet. Verified SSO and
service-to-service authentication remain future work.

For Agent Registry behavior, local setup, and testing, see [Agent Registry documentation](docs/registry.md).

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before making
changes. AI-generated changes remain unstaged and uncommitted for human review.
