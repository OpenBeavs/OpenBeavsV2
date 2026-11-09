.PHONY: run dev stop down dev-back dev-front test test-backend test-frontend lint seed migrate help

# ── Development ───────────────────────────────────────────────────────────────
# Starts backend and frontend concurrently in one terminal
run:
	python scripts/dev.py start

dev: run

# Stops all running development servers and frees ports 8000 and 5173
stop:
	python scripts/dev.py stop

down: stop

# Run individual services in their own terminal if desired
dev-back:
	cd backend && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

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
	@echo "  make run        Start all dev servers concurrently in 1 terminal"
	@echo "  make stop       Stop all running servers and free ports (8000, 5173)"
	@echo "  make dev-back   Start backend server only (port 8000)"
	@echo "  make dev-front  Start frontend server only (port 5173)"
	@echo "  make test       Run backend (pytest) and frontend (vitest) tests"
	@echo "  make lint       Run ruff and svelte-check"
	@echo "  make seed       Seed initial agents into the database"
	@echo "  make migrate    Run database migrations (Alembic)"
	@echo "────────────────────────────────────────────────────────────────────"
	@echo ""

