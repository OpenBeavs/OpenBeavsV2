.PHONY: run dev stop down dev-back dev-chris dev-registry dev-front test test-backend test-frontend lint seed migrate help

# The launchers use only Python's standard library. Each service, test suite and
# migration runs in its own package's environment, through uv.
PYTHON ?= uv run --no-project --python 3.12 python

# ── Development ───────────────────────────────────────────────────────────────
# Starts all 4 services (Agent Registry, Conversation Agent, Application Services,
# Web UI) with start-dev.py
run:
	$(PYTHON) start-dev.py

dev: run

# Stops whatever listens on the stack's ports: 8000, 8001, 8010, 5173 and 8080
stop:
	$(PYTHON) scripts/dev.py stop

down: stop

# Run individual services, each in its own terminal, with start-dev.py's settings
dev-registry:
	$(PYTHON) scripts/dev.py start agent-registry

dev-chris:
	$(PYTHON) scripts/dev.py start conversation-agent

dev-back:
	$(PYTHON) scripts/dev.py start application-services

dev-front:
	$(PYTHON) scripts/dev.py start web-ui

# ── Testing & Quality ─────────────────────────────────────────────────────────
test: test-backend test-frontend

test-backend:
	cd agent-registry && uv run pytest
	cd chat-system/conversation-agent && uv run pytest
	cd chat-system/application-services && uv run pytest
	cd tests/end-to-end && uv run pytest

test-frontend:
	cd chat-system/web-ui && npm test

lint:
	cd agent-registry && uv run ruff check .
	cd chat-system/conversation-agent && uv run ruff check .
	cd chat-system/application-services && uv run ruff check .
	cd tests/end-to-end && uv run ruff check .
	cd chat-system/web-ui && npm run lint

# ── Database ──────────────────────────────────────────────────────────────────
# Each owner's own database (DATABASE_URL, relative to the owner's folder) and history
seed:
	cd agent-registry && uv run python -m agent_registry.database.seed_agents

migrate:
	cd agent-registry && uv run alembic upgrade head
	cd chat-system/application-services && uv run alembic upgrade head

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "OpenBeavs v2 — Developer Commands"
	@echo "────────────────────────────────────────────────────────────────────"
	@echo "  make run          Start all 4 dev servers with start-dev.py:"
	@echo "                    - Agent Registry (8001), Conversation Agent (8000),"
	@echo "                      Application Services (8010), Web UI (8080 or 5173)"
	@echo "  make stop         Stop whatever listens on the stack's ports"
	@echo "  make dev-registry Start the Agent Registry only (port 8001)"
	@echo "  make dev-chris    Start the Conversation Agent only (port 8000)"
	@echo "  make dev-back     Start Application Services only (port 8010, reloads)"
	@echo "  make dev-front    Start the Web UI only (port 8080 or 5173)"
	@echo "  make test         Run every Python suite (pytest) and the Web UI's unit tests (vitest)"
	@echo "  make lint         Run ruff in every Python folder, and ESLint and svelte-check"
	@echo "  make seed         Seed the sample agents into the Agent Registry's database"
	@echo "  make migrate      Migrate the Agent Registry's and Application Services' databases"
	@echo "────────────────────────────────────────────────────────────────────"
	@echo ""
