# ---------------------------------------------------------------------------
# ClaimGuard AI — developer targets
#
# Windows-friendly: targets only call `uv run ...` and `docker compose ...`
# (no bash-only syntax); run Make from Git Bash, WSL, or a POSIX shell.
# ---------------------------------------------------------------------------

UV      ?= uv
COMPOSE ?= docker compose

.PHONY: install lint typecheck test test-all migrate seed demo-smoke up down

install: ## Install all dependencies (project + extras) into the project venv
	$(UV) sync --all-extras

lint: ## Ruff lint + format check (no writes)
	$(UV) run ruff check .
	$(UV) run ruff format --check .

typecheck: ## Pyright strict type check (see [tool.pyright] in pyproject.toml)
	$(UV) run pyright

test: ## Fast tests — unit + integration, no LLM, no e2e (daily loop)
	$(UV) run pytest -m "not llm and not e2e"

test-all: ## Full suite — requires live infra (DB, and LLM for e2e/llm markers)
	$(UV) run pytest

migrate: ## Apply Alembic migrations to the local database
	$(UV) run alembic upgrade head

seed: ## Load synthetic (Velodoc) demo data into the local database
	$(UV) run claimguard seed

demo-smoke: ## End-to-end smoke run of the demo pipeline (no LLM)
	$(UV) run claimguard demo-smoke

up: ## Build and start the full stack — db, otel-lgtm, api, web
	$(COMPOSE) up --build -d

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down