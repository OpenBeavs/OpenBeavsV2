.PHONY: run dev stop down dev-back dev-registry dev-front test test-backend test-frontend lint seed migrate help

# ── Development ───────────────────────────────────────────────────────────────
# Starts all 4 services (registry, chris, backend, frontend) using the team's start-dev.py
run:
	python start-dev.py

dev: run

# Stops all running development servers and frees ports 8000, 8001, 8010, and 5173
stop:
	python scripts/dev.py stop

down: stop

# Run individual services in their own terminal if desired
dev-back:
	cd backend && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-registry:
	cd backend && python -m uvicorn app.registry.a2a_app:create_standalone_app --factory --host 127.0.0.1 --port 8001

dev-front:
	cd frontend && npm run dev

# ── Testing & Quality ─────────────────────────────────────────────────────────
test: test-backend test-frontend

test-backend:
	cd backend && python -m pytest

test-frontend:
	cd frontend && npm test

lint:
	cd backend && python -m ruff check .
	cd frontend && npm run check

# ── Database ──────────────────────────────────────────────────────────────────
seed:
	cd backend && python -m app.db.seed_agents

migrate:
	cd backend && alembic upgrade head

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "OpenBeavs v2 — Developer Commands"
	@echo "────────────────────────────────────────────────────────────────────"
	@echo "  make run          Start all 3 dev servers in 1 terminal:"
	@echo "                    - Backend (8000), Registry (8001), Frontend (5173)"
	@echo "  make stop         Stop all running servers and free ports"
	@echo "  make dev-back     Start backend server only (port 8000)"
	@echo "  make dev-registry Start registry A2A service only (port 8001)"
	@echo "  make dev-front    Start frontend server only (port 5173)"
	@echo "  make test         Run backend (pytest) and frontend (vitest) tests"
	@echo "  make lint         Run ruff and svelte-check"
	@echo "  make seed         Seed initial agents into the database"
	@echo "  make migrate      Run database migrations (Alembic)"
	@echo "────────────────────────────────────────────────────────────────────"
	@echo ""
