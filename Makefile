# Convenience targets. Every one of these is a command you would otherwise type,
# and none of them hide anything you would want to see — a Makefile that wraps a
# command in three layers is a Makefile nobody trusts when it fails.
#
# The layout moved at M1: the Python package lives in ./backend, the Next.js app
# in ./frontend, and the whole system runs in containers. Targets that assumed a
# root-level package are gone rather than kept limping.

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.DEFAULT_GOAL := help
.PHONY: help venv install install-neural up down logs ps rebuild bootstrap doctor \
        migrate migrate-down check test test-fast lint types web-install web-dev \
        web-test web-build bench bench-neural ask clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

# ------------------------------------------------------------------ python env

venv: ## Create the virtualenv
	python3 -m venv $(VENV)

install: venv ## Install the backend in editable mode with dev extras
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e "./backend[dev]"

install-neural: install ## Also install sentence-transformers (~2.5GB, optional)
	$(PIP) install -q -e "./backend[neural]"

# ------------------------------------------------------------------ the stack

up: ## Bring the whole stack up (nine services, web included)
	docker compose up -d

down: ## Stop everything; volumes are preserved
	docker compose down

logs: ## Follow logs from every service
	docker compose logs -f

ps: ## Show service health
	docker compose ps

rebuild: ## Rebuild the images that build from source and restart them
	docker compose up -d --build api worker realtime web

bootstrap: ## First org + admin + system roles + provider rows. Idempotent.
	@echo "Password comes from MNEMOS_BOOTSTRAP_ADMIN_PASSWORD or an interactive"
	@echo "prompt — never from argv, which is world-readable in /proc."
	docker compose exec api mnemosctl bootstrap \
	  --org-slug $(or $(ORG),mnemos) \
	  --org-name "$(or $(ORG_NAME),Mnemos)" \
	  --admin-email $(or $(EMAIL),admin@mnemos.local)

doctor: ## Print what the database actually looks like right now
	docker compose exec api mnemosctl db doctor

# ------------------------------------------------------------------ migrations

# Run through the `migrate` service rather than the host venv. It is the only
# service whose DSN is the table owner's, and it resolves `postgres` over the
# compose network — whereas `core/config.py`'s default points at localhost:5432,
# which on a machine that already runs its own Postgres (this one does; compose
# maps the stack's to 15432) is a different server entirely. Running these from
# the host silently targets the wrong database or fails to authenticate.

migrate: ## Apply migrations to head
	docker compose run --rm migrate alembic upgrade head

migrate-down: ## Roll back one revision
	docker compose run --rm migrate alembic downgrade -1

check: ## Fail if the models and the migrations have drifted
	docker compose run --rm migrate alembic check

# ------------------------------------------------------------------ the gate
# These four are what CI runs (.github/workflows/ci.yml). Run them before you
# push and the pull request will not be the place you find out.

test: ## Full backend suite (needs Docker: testcontainers + a live Keycloak)
	cd backend && ../$(VENV)/bin/python -m pytest

test-fast: ## Backend suite minus the containerised suites
	cd backend && ../$(VENV)/bin/python -m pytest \
	  --ignore=tests/test_tenant_isolation.py \
	  --ignore=tests/test_bootstrap.py \
	  --ignore=tests/test_session_store.py

lint: ## Lint and format-check. _v1/ is quarantined until it is ported (A2/C4).
	cd backend && ../$(VENV)/bin/ruff check . --exclude src/mnemos/_v1
	cd backend && ../$(VENV)/bin/ruff format --check . \
	  --exclude src/mnemos/_v1 --exclude tests/test_invariants.py

types: ## mypy --strict over the non-quarantined tree
	cd backend && ../$(VENV)/bin/mypy --strict \
	  src/mnemos/core src/mnemos/features src/mnemos/entrypoints

# ------------------------------------------------------------------ frontend

web-install: ## Install frontend dependencies
	cd frontend && npm ci

web-dev: ## Run the Next.js dev server outside the container
	cd frontend && npm run dev

web-test: ## Vitest + Testing Library
	cd frontend && npm run test

web-build: ## Lint, typecheck and production build — the frontend half of CI
	cd frontend && npm run lint && npx tsc --noEmit && npm run build

# ------------------------------------------------------------------ v0.1 bench
# The v0.1 kernel is quarantined in backend/src/mnemos/_v1/ and still owns the
# published benchmark. It is ported in halves — retrieval in A2, memory and the
# context compiler in C4 — and the numbers are re-measured on Postgres there.
# Until then these run against SQLite, which is what the README says they are.

bench: ## Benchmark with the zero-download embedder
	cd backend && ../$(VENV)/bin/python -m mnemos._v1.cli bench \
	  --budgets 800,1500,3000 --json ../bench_results/hashing.json

bench-neural: ## Benchmark with bge-small-en-v1.5 (requires install-neural)
	cd backend && ../$(VENV)/bin/python -m mnemos._v1.cli bench \
	  --budgets 800,1500,3000 --embedder neural --json ../bench_results/neural.json

ask: ## Compile one question. Usage: make ask Q="your question"
	cd backend && ../$(VENV)/bin/python -m mnemos._v1.cli ask "$(Q)" --explain

clean: ## Remove caches and local data
	rm -rf .pytest_cache .ruff_cache .mypy_cache .data
	rm -rf frontend/.next frontend/tsconfig.tsbuildinfo
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
