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
.PHONY: help venv install install-neural up wait down logs ps rebuild bootstrap demo-seed \
        doctor migrate migrate-down check test test-fast lint types web-install web-dev \
        web-test web-build bench ask clean

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

up: ## Bring the whole stack up (ten services, web and demo MCP included)
	docker compose up -d

wait: ## Block until /readyz is fully green. First run also pulls the ~2GB Ollama model
	@echo "Waiting for postgres, redis, ollama (pulls the model on first run) and object storage..."
	@for i in $$(seq 1 100); do \
	  if curl -sf http://localhost:8000/readyz 2>/dev/null | grep -q '"status":"ready"'; then \
	    echo "ready."; exit 0; \
	  fi; \
	  sleep 3; \
	done; \
	echo "Still not ready after 5 minutes. Check: docker compose logs ollama-init api"; exit 1

down: ## Stop everything; volumes are preserved
	docker compose down

logs: ## Follow logs from every service
	docker compose logs -f

ps: ## Show service health
	docker compose ps

rebuild: ## Rebuild the images that build from source and restart them
	docker compose up -d --build api worker realtime web demo-mcp

bootstrap: ## First org + admin + system roles + provider rows. Idempotent.
	@echo "Password comes from MNEMOS_BOOTSTRAP_ADMIN_PASSWORD or an interactive"
	@echo "prompt — never from argv, which is world-readable in /proc."
	docker compose exec -e MNEMOS_BOOTSTRAP_ADMIN_PASSWORD api mnemosctl bootstrap \
	  --org-slug $(or $(ORG),mnemos) \
	  --org-name "$(or $(ORG_NAME),Mnemos)" \
	  --admin-email $(or $(EMAIL),admin@mnemos.local)

demo-seed: bootstrap ## Deterministic demo state for docs/Demo.md: warehouse + glossary + the fixture source. Idempotent.
	docker compose exec api mnemosctl datasource introspect --org-slug $(or $(ORG),mnemos)
	docker compose exec api mnemosctl datasource seed-glossary --org-slug $(or $(ORG),mnemos)
	docker compose exec api mnemosctl connector register \
	  --org-slug $(or $(ORG),mnemos) --slug demo-fixtures --name "Demo fixtures" \
	  --kind local_fs --root /fixtures/sources
	@echo "Demo state ready — follow docs/Demo.md."

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
	  src/mnemos/core src/mnemos/features src/mnemos/entrypoints \
	  src/mnemos/flows src/mnemos/platform

# ------------------------------------------------------------------ frontend

web-install: ## Install frontend dependencies
	cd frontend && npm ci

web-dev: ## Run the Next.js dev server outside the container
	cd frontend && npm run dev

web-test: ## Vitest + Testing Library
	cd frontend && npm run test

web-build: ## Lint, typecheck and production build — the frontend half of CI
	cd frontend && npm run lint && npx tsc --noEmit && npm run build

# --------------------------------------------------------------- Postgres bench
# Self-contained: starts pgvector Postgres with testcontainers, applies the real
# migrations, seeds the frozen corpus, then uses the current retrieval, memory,
# and compiler paths. The JSON records this exact reproduction command.

bench: ## Benchmark with the zero-download embedder
	cd backend && ../$(VENV)/bin/python -m mnemos.features.context.benchmark \
	  --budgets 800,1500,3000 --json ../bench_results/hashing.json

ask: ## Compile one question. Usage: make ask Q="your question"
	cd backend && ../$(VENV)/bin/python -m mnemos._v1.cli ask "$(Q)" --explain

clean: ## Remove caches and local data
	rm -rf .pytest_cache .ruff_cache .mypy_cache .data
	rm -rf frontend/.next frontend/tsconfig.tsbuildinfo
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
