VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.DEFAULT_GOAL := help
.PHONY: help venv install install-neural serve bench bench-neural ask test lint clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

venv: ## Create the virtualenv
	python3 -m venv $(VENV)

install: venv ## Install the package (zero-download default path)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e ".[dev]"

install-neural: install ## Also install sentence-transformers (~2.5GB, optional)
	$(PIP) install -q -e ".[neural]"

serve: ## Run the inspector UI on http://127.0.0.1:8000
	$(PY) -m mnemos.cli serve

bench: ## Benchmark with the zero-download embedder
	$(PY) -m mnemos.cli bench --budgets 800,1500,3000 --json bench_results/hashing.json

bench-neural: ## Benchmark with bge-small-en-v1.5 (requires install-neural)
	$(PY) -m mnemos.cli bench --budgets 800,1500,3000 --embedder neural \
	  --json bench_results/neural.json

ask: ## Compile one question. Usage: make ask Q="your question"
	$(PY) -m mnemos.cli ask "$(Q)" --explain

test: ## Run the test suite
	$(PY) -m pytest -q

lint: ## Lint and type-check
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/ruff format --check src tests

clean: ## Remove caches and local data
	rm -rf .pytest_cache .ruff_cache .mypy_cache .data
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
