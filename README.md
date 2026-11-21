# OpenBeavs v2

The OSU AI hub prototype, with a standalone Chris frontend and FastAPI backend.

- `frontend/`: Svelte chat interface and read-only registered-agent directory.
- `backend/`: Chris routing, direct Gemini answers, and relational persistence.
- `docs/`: API, frontend setup, and database documentation.

Start with [local setup and frontend integration](docs/frontend.md), then see
[Chris's API](docs/chris.md). The frontend runs independently of the original
Open WebUI backend. Real agent calls and verified SSO are future backend work.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before making
changes. AI-generated changes remain unstaged and uncommitted for human review.
